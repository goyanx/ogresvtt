(ns ogres.app.ai.tool-dispatch
  (:require [datascript.core :as ds]
            [ogres.app.ai.narration :as narration]
            [ogres.app.audio :as audio]
            [ogres.app.collision :as collision]
            [ogres.app.const :refer [grid-size]]
            [ogres.app.pathfind :as pathfind]
            [ogres.app.vec :refer [Vec2]]))

(defn ^:private current-scene
  "Returns the scene the local user is currently viewing."
  [db]
  (-> (ds/entity db [:db/ident :user])
      :user/camera :camera/scene))

(defn ^:private scene-grid-size
  "Returns the active scene grid size in pixels."
  [db]
  (or (:scene/grid-size (current-scene db))
      grid-size))

(defn ^:private scene-geometry
  "Returns `[walls doors]` for the scene the local user is viewing."
  [db]
  (let [scene (current-scene db)]
    [(or (:scene/walls scene) [])
     (or (:scene/doors scene) [])]))

(defn ^:private valid-token?
  "Returns true if the given entity ID exists and is a token in the current scene."
  [db token-id]
  (let [entity (ds/entity db token-id)]
    (and (some? entity)
         (= (:object/type entity) :token/token))))

(def ^:private direction->delta
  {"north"     [ 0 -1]
   "south"     [ 0  1]
   "east"      [ 1  0]
   "west"      [-1  0]
   "northeast" [ 1 -1]
   "northwest" [-1 -1]
   "southeast" [ 1  1]
   "southwest" [-1  1]})

(defn ^:private snap-to-grid
  "Snaps a pixel coordinate to the nearest grid cell center."
  [x y gs]
  (let [gs (or gs grid-size)
        hs (/ gs 2)
        sx (+ (* (js/Math.round (/ (- x hs) gs)) gs) hs)
        sy (+ (* (js/Math.round (/ (- y hs) gs)) gs) hs)]
    (Vec2. sx sy)))

(defmulti dispatch-tool
  "Dispatches a validated AI DM tool call to the OgresVTT event system."
  (fn [_dispatch _db tool-name _args _opts] tool-name))

;; list_tokens is a query tool handled by the LangGraph sidecar.
;; In direct mode the LLM already has token info in the system prompt,
;; so this is a no-op on the client side.
(defmethod dispatch-tool "list_tokens"
  [_dispatch _db _ _args _opts]
  {:ok true :note "list_tokens is resolved server-side in LangGraph mode"})

(defmethod dispatch-tool "show_map"
  [dispatch _db _ args _opts]
  (dispatch :ai-dm/show-map args)
  {:ok true :note "map switch/show request dispatched"})

(defmethod dispatch-tool "narrate"
  [dispatch _db _ {:keys [text]} {:keys [on-narrate on-ai-narration]}]
  (when (narration/narration-text-visible? text)
    (dispatch :narration/append text "ai")
    (when on-narrate (on-narrate text)))
  (when (and on-ai-narration (narration/narration-text-visible? text))
    (on-ai-narration text))
  {:ok true})

(defmethod dispatch-tool "move_player_token"
  [dispatch db _ {:keys [token_id direction squares]} _opts]
  (if (valid-token? db token_id)
    (if-let [[dx dy] (direction->delta (or direction "north"))]
      (let [gs      (scene-grid-size db)
            n       (max 1 (or squares 1))
            origin  (:object/point (ds/entity db token_id))
            ox      (.-x origin)
            oy      (.-y origin)
            tx      (+ ox (* dx n gs))
            ty      (+ oy (* dy n gs))
            [walls doors] (scene-geometry db)]
        (if (collision/path-blocked? walls doors ox oy tx ty)
          {:ok false :reason "Path is blocked by a wall or closed door."}
          (do (dispatch :objects/translate token_id (Vec2. (- tx ox) (- ty oy)))
              {:ok true :moved {:squares n :direction direction}})))
      {:ok false :reason (str "Unknown direction: " direction)})
    {:ok false :reason (str "Token " token_id " not found.")}))

(defmethod dispatch-tool "move_token"
  [dispatch db _ {:keys [token_id x y]} _opts]
  (if (valid-token? db token_id)
    (let [entity (ds/entity db token_id)
          flags  (:token/flags entity)]
      (if (contains? flags :player)
        {:ok false :reason "Cannot move player tokens."}
        (let [target (snap-to-grid x y (scene-grid-size db))
              origin (:object/point entity)
              ox (.-x origin) oy (.-y origin)
              tx (.-x target) ty (.-y target)
              [walls doors] (scene-geometry db)]
          (if (collision/path-blocked? walls doors ox oy tx ty)
            {:ok false :reason "Path is blocked by a wall or closed door."}
            (do (dispatch :objects/translate token_id
                          (Vec2. (- tx ox) (- ty oy)))
                {:ok true})))))
    {:ok false :reason (str "Token " token_id " not found.")}))

(defmethod dispatch-tool "spawn_token"
  [dispatch db _ {:keys [label x y size]} _opts]
  (let [user   (ds/entity db [:db/ident :user])
        camera (:user/camera user)
        scene  (:camera/scene camera)
        point  (snap-to-grid x y (:scene/grid-size scene))
        shift  (:camera/point camera)
        scale  (or (:camera/scale camera) 1)
        ;; Convert scene coords to screen coords expected by :token/create.
        ;; :token/create does: screen-point / scale + shift = scene-point
        ;; So: screen-point = (scene-point - shift) * scale
        screen (Vec2. (* (- (.-x point) (.-x shift)) scale)
                      (* (- (.-y point) (.-y shift)) scale))]
    ;; Use raw DataScript transactions since :token/create expects screen coords
    ;; and an image hash. Instead, transact directly.
    (dispatch :ai-dm/spawn-token label point size)
    {:ok true}))

(defmethod dispatch-tool "remove_token"
  [dispatch db _ {:keys [token_id]} _opts]
  (if (valid-token? db token_id)
    (let [entity (ds/entity db token_id)
          flags  (:token/flags entity)]
      (if (contains? flags :player)
        {:ok false :reason "Cannot remove player tokens."}
        (do (dispatch :objects/remove #{token_id})
            {:ok true})))
    {:ok false :reason (str "Token " token_id " not found.")}))

(def ^:private token-meta-max-chars
  4000)

(defmethod dispatch-tool "update_token_attribute"
  [dispatch db _ {:keys [token_id text mode]} _opts]
  (if (valid-token? db token_id)
    (let [raw      (if (string? text) text (str text))
          existing (or (:token/meta (ds/entity db token_id)) "")
          merged   (if (and (= mode "append") (seq existing) (seq raw))
                     (str existing "\n" raw)
                     raw)
          short    (if (> (count merged) token-meta-max-chars)
                     (subs merged 0 token-meta-max-chars)
                     merged)]
      (dispatch :token/change-meta [token_id] short)
      {:ok true :updated token_id :mode (or mode "replace")})
    {:ok false :reason (str "Token " token_id " not found.")}))

(defmethod dispatch-tool "update_hp"
  [dispatch db _ {:keys [token_id hp]} _opts]
  (if (valid-token? db token_id)
    (do (dispatch :initiative/change-health token_id (fn [_ v] v) (str hp))
        {:ok true})
    {:ok false :reason (str "Token " token_id " not found.")}))

(defmethod dispatch-tool "apply_damage"
  [dispatch db _ {:keys [token_id amount mode]} _opts]
  (if (valid-token? db token_id)
    (if (and (number? amount) (not (neg? amount)))
      (do
        (dispatch :initiative/change-health token_id
                  (fn [old v]
                    (let [base  (if (number? old) old 0)
                          delta (if (= mode "healing") v (- v))
                          next  (+ base delta)]
                      (js/Math.max 0 next)))
                  (str amount))
        {:ok true})
      {:ok false :reason (str "Invalid amount: " amount ". Expected a non-negative number.")})
    {:ok false :reason (str "Token " token_id " not found.")}))

(defmethod dispatch-tool "roll_initiative"
  [dispatch db _ {:keys [token_ids]} _opts]
  (let [valid-ids (filterv #(valid-token? db %) token_ids)]
    (when (seq valid-ids)
      (dispatch :initiative/toggle valid-ids true)
      (dispatch :initiative/roll-all))
    {:ok true :added (count valid-ids)}))

(defmethod dispatch-tool "advance_turn"
  [dispatch _db _ _args _opts]
  (dispatch :initiative/next)
  {:ok true})

(defmethod dispatch-tool "leave_initiative"
  [dispatch _db _ _args _opts]
  (dispatch :initiative/leave)
  {:ok true})

(defmethod dispatch-tool "plan_path"
  [_dispatch db _ {:keys [from_x from_y to_x to_y]} _opts]
  (let [[walls doors] (scene-geometry db)]
    (if-let [waypoints (pathfind/path-waypoints
                        walls doors from_x from_y to_x to_y)]
      {:ok true :waypoints waypoints}
      {:ok false :reason "No walkable path found between those points."})))

(defmethod dispatch-tool "set_ambience"
  [_dispatch _db _ {:keys [mood]} _opts]
  (audio/set-ambience! (or mood "none")))

(defmethod dispatch-tool "play_sound"
  [_dispatch _db _ {:keys [effect]} _opts]
  (audio/play-effect! (or effect "")))

(defmethod dispatch-tool "set_door_state"
  [dispatch db _ {:keys [door_index closed]} _opts]
  (let [[_ doors] (scene-geometry db)]
    (if (and (integer? door_index)
             (<= 0 door_index)
             (< door_index (count doors)))
      (do (dispatch :scene/set-door-state door_index (boolean closed))
          {:ok true})
      {:ok false :reason (str "No door with index " door_index ".")})))

(defmethod dispatch-tool :default
  [_ _ tool-name _ _opts]
  {:ok false :reason (str "Unknown tool: " tool-name)})

(defn dispatch-tool-calls
  "Processes a sequence of tool calls from the LLM response, dispatching
   each to the OgresVTT event system. Returns a vector of results."
  [dispatch db tool-calls & [opts]]
  (into []
    (for [tc tool-calls
          :let [fname (get-in tc [:function :name])
                raw   (get-in tc [:function :arguments])
                args  (try
                        (js->clj (js/JSON.parse raw) :keywordize-keys true)
                        (catch :default _ {}))]]
      (try
        (dispatch-tool dispatch db fname args (or opts {}))
        (catch :default e
          {:ok false :reason (.-message e)})))))
