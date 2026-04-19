(ns ogres.app.ai.tool-dispatch
  (:require [datascript.core :as ds]
            [ogres.app.ai.text :as ai-text]
            [ogres.app.const :refer [grid-size half-size]]
            [ogres.app.vec :refer [Vec2]]))

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
  [x y]
  (let [gs grid-size
        hs half-size
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

(defmethod dispatch-tool "narrate"
  [dispatch _db _ {:keys [text]} {:keys [on-narrate]}]
  (if-let [narration (ai-text/narrative-only text)]
    (do
      (dispatch :narration/append narration "ai")
      (when on-narrate (on-narrate narration))
      {:ok true})
    {:ok false :reason "Narration contained only structured output."}))

(defmethod dispatch-tool "move_player_token"
  [dispatch db _ {:keys [token_id direction squares]} _opts]
  (if (valid-token? db token_id)
    (if-let [[dx dy] (direction->delta (or direction "north"))]
      (let [n     (max 1 (or squares 1))
            entity (:object/point (ds/entity db token_id))
            delta  (Vec2. (* dx n grid-size) (* dy n grid-size))]
        (dispatch :objects/translate token_id delta)
        {:ok true :moved {:squares n :direction direction}})
      {:ok false :reason (str "Unknown direction: " direction)})
    {:ok false :reason (str "Token " token_id " not found.")}))

(defmethod dispatch-tool "move_token"
  [dispatch db _ {:keys [token_id x y]} _opts]
  (if (valid-token? db token_id)
    (let [entity (ds/entity db token_id)
          flags  (:token/flags entity)]
      (if (contains? flags :player)
        {:ok false :reason "Cannot move player tokens."}
        (let [target (snap-to-grid x y)
              origin (:object/point entity)
              delta  (Vec2. (- (.-x target) (.-x origin))
                            (- (.-y target) (.-y origin)))]
          (dispatch :objects/translate token_id delta)
          {:ok true})))
    {:ok false :reason (str "Token " token_id " not found.")}))

(defmethod dispatch-tool "spawn_token"
  [dispatch db _ {:keys [label x y size]} _opts]
  (let [user   (ds/entity db [:db/ident :user])
        camera (:user/camera user)
        scene  (:camera/scene camera)
        point  (snap-to-grid x y)
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

(defmethod dispatch-tool "update_hp"
  [dispatch db _ {:keys [token_id hp]} _opts]
  (if (valid-token? db token_id)
    (do (dispatch :initiative/change-health token_id (fn [_ v] v) (str hp))
        {:ok true})
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
