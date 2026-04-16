(ns ogres.app.ai.tool-dispatch
  (:require [datascript.core :as ds]
            [ogres.app.const :refer [grid-size half-size]]
            [ogres.app.vec :refer [Vec2]]))

(defn ^:private valid-token?
  "Returns true if the given entity ID exists and is a token in the current scene."
  [db token-id]
  (let [entity (ds/entity db token-id)]
    (and (some? entity)
         (= (:object/type entity) :token/token))))

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
  (fn [_dispatch _db tool-name _args] tool-name))

(defmethod dispatch-tool "narrate"
  [dispatch _db _ {:keys [text]}]
  (when (seq text)
    (dispatch :narration/append text "ai"))
  {:ok true})

(defmethod dispatch-tool "move_token"
  [dispatch db _ {:keys [token_id x y]}]
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
  [dispatch db _ {:keys [label x y size]}]
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
  [dispatch db _ {:keys [token_id]}]
  (if (valid-token? db token_id)
    (let [entity (ds/entity db token_id)
          flags  (:token/flags entity)]
      (if (contains? flags :player)
        {:ok false :reason "Cannot remove player tokens."}
        (do (dispatch :objects/remove #{token_id})
            {:ok true})))
    {:ok false :reason (str "Token " token_id " not found.")}))

(defmethod dispatch-tool "update_hp"
  [dispatch db _ {:keys [token_id hp]}]
  (if (valid-token? db token_id)
    (do (dispatch :initiative/change-health token_id (fn [_ v] v) (str hp))
        {:ok true})
    {:ok false :reason (str "Token " token_id " not found.")}))

(defmethod dispatch-tool "roll_initiative"
  [dispatch db _ {:keys [token_ids]}]
  (let [valid-ids (filterv #(valid-token? db %) token_ids)]
    (when (seq valid-ids)
      (dispatch :initiative/toggle valid-ids true)
      (dispatch :initiative/roll-all))
    {:ok true :added (count valid-ids)}))

(defmethod dispatch-tool "advance_turn"
  [dispatch _db _ _args]
  (dispatch :initiative/next)
  {:ok true})

(defmethod dispatch-tool :default
  [_ _ tool-name _]
  {:ok false :reason (str "Unknown tool: " tool-name)})

(defn dispatch-tool-calls
  "Processes a sequence of tool calls from the LLM response, dispatching
   each to the OgresVTT event system. Returns a vector of results."
  [dispatch db tool-calls]
  (into []
    (for [tc tool-calls
          :let [fname (get-in tc [:function :name])
                raw   (get-in tc [:function :arguments])
                args  (try
                        (js->clj (js/JSON.parse raw) :keywordize-keys true)
                        (catch :default _ {}))]]
      (try
        (dispatch-tool dispatch db fname args)
        (catch :default e
          {:ok false :reason (.-message e)})))))
