(ns ogres.app.ai.core
  "AI Dungeon Master orchestrator. Manages configuration, the turn timer,
   LLM calls, and tool call dispatch. Runs entirely in the host's browser."
  (:require [datascript.core :as ds]
            [ogres.app.ai.prompt :as prompt]
            [ogres.app.ai.text :as ai-text]
            [ogres.app.ai.tool-dispatch :as tool-dispatch]
            [ogres.app.ai.backends.ollama :as ollama]
            [ogres.app.ai.backends.grok :as grok]
            [ogres.app.ai.backends.langgraph :as langgraph]
            [ogres.app.ai.vision :as vision]
            [ogres.app.ai.voice :as voice]
            [ogres.app.const :refer [grid-size]]
            [ogres.app.hooks :as hooks]
            [ogres.app.provider.idb :as idb]
            [ogres.app.provider.state :as state]
            [uix.core :as uix :refer [defui $]]))

;; ---------------------------------------------------------------------------
;; Configuration (persisted to localStorage)
;; ---------------------------------------------------------------------------

(def default-config
  {:enabled        false
   :backend        :ollama
   :endpoint       "http://localhost:11434"
   :model          "qwen2.5:14b-instruct-q4_K_M"
   :lg-endpoint    "http://localhost:8765"
   :scenario       ""
   :auto-approve   true
   :interval-ms    15000
   :voice-enabled  false
   :voice-id       "bm_george"
   :voice-speed    0.95
   :vision-enabled false
   :vision-model   "qwen2.5-vl:7b"})

(defn load-config
  "Loads AI DM configuration from localStorage, merging with defaults."
  []
  (if-let [raw (.getItem js/localStorage "ai-dm-config")]
    (try
      (let [parsed (js->clj (js/JSON.parse raw) :keywordize-keys true)]
        (merge default-config
               (update parsed :backend #(if (string? %) (keyword %) %))))
      (catch :default _ default-config))
    default-config))

(defn save-config!
  "Persists AI DM configuration to localStorage."
  [config]
  (.setItem js/localStorage "ai-dm-config"
    (js/JSON.stringify (clj->js (update config :backend name)))))

;; ---------------------------------------------------------------------------
;; Context — shared between core and panel components
;; ---------------------------------------------------------------------------

(def context (uix/create-context))

;; ---------------------------------------------------------------------------
;; LLM call
;; ---------------------------------------------------------------------------

(defn ^:private call-backend
  "Dispatches a chat completion request to the configured backend."
  [config messages]
  (case (:backend config)
    :ollama    (ollama/chat-completion
                 {:endpoint (:endpoint config)
                  :model    (:model config)
                  :messages messages})
    :grok      (grok/chat-completion
                 {:model    (:model config)
                  :messages messages})
    :langgraph (langgraph/chat-completion
                 {:lg-endpoint  (:lg-endpoint config)
                  :llm-endpoint (:endpoint config)
                  :llm-model    (:model config)
                  :messages     messages})
    (js/Promise.reject (js/Error. (str "Unknown backend: " (:backend config))))))

;; ---------------------------------------------------------------------------
;; Turn execution
;; ---------------------------------------------------------------------------

(defn run-turn!
  "Executes a single AI DM turn: serialize state, call LLM, dispatch tool calls."
  [conn dispatch config idb-read history set-history set-pending]
  (set-pending true)
  (let [token-vision-pull
        [:db/id :token/flags :token/light :token/size :object/point]
        db         @conn
        user       (ds/entity db [:db/ident :user])
        scene      (-> user :user/camera :camera/scene)
        image-hash (-> scene :scene/image :image/hash)
        gs         (or (:scene/grid-size scene) grid-size)
        origin     (:scene/grid-origin scene)
        all-tokens (when (:scene/tokens scene)
                     (ds/pull-many db token-vision-pull
                       (map :db/id (:scene/tokens scene))))
        user-msg   {:role "user"
                    :content "It is your turn. Review the game state and take appropriate actions."}
        terrain-p  (if (and (:vision-enabled config) image-hash idb-read (seq all-tokens))
                     (vision/detect-all-terrain! all-tokens
                       {:idb-read   idb-read
                        :endpoint   (:endpoint config)
                        :model      (or (:vision-model config) "qwen3-vl:8b")
                        :image-hash image-hash
                        :scene-gs   gs
                        :origin-x   (if origin (.-x origin) 0)
                        :origin-y   (if origin (.-y origin) 0)})
                     (js/Promise.resolve {}))
        visibility-p
        (if (and (:vision-enabled config) image-hash idb-read (seq all-tokens))
          (vision/detect-local-visibility! all-tokens
            {:idb-read   idb-read
             :endpoint   (:endpoint config)
             :model      (or (:vision-model config) "qwen3-vl:8b")
             :image-hash image-hash
             :scene-gs   gs
             :origin-x   (if origin (.-x origin) 0)
             :origin-y   (if origin (.-y origin) 0)
             :default-squares 10})
          (js/Promise.resolve {}))]
    (-> (js/Promise.all #js [terrain-p visibility-p])
        (.then
          (fn [results]
            (let [terrain-map    (or (aget results 0) {})
                  visibility-map (or (aget results 1) {})
                  game-state     (prompt/serialize-game-state db terrain-map visibility-map)
                  system-msg {:role "system"
                              :content (prompt/build-system-prompt
                                         (:scenario config) game-state gs)}
                  messages   (into [system-msg] (conj (vec history) user-msg))]
              (call-backend config messages))))
        (.then
          (fn [response]
            (let [choice     (first (:choices response))
                  message    (:message choice)
                  tool-calls (:tool_calls message)
                  content    (:content message)
                  speak!     (fn [text]
                               (when (and (:voice-enabled config) (seq text))
                                 (voice/speak! text
                                   {:sidecar-url (:lg-endpoint config)
                                    :voice       (:voice-id config)
                                    :speed       (:voice-speed config)})))]
              (when (and (seq content) (empty? tool-calls))
                (if-let [narration (ai-text/narrative-only content)]
                  (do
                    (dispatch :narration/append narration "ai")
                    (speak! narration))
                  (let [fallback "The room holds a tense silence as everyone studies the scene."]
                    (dispatch :narration/append fallback "ai")
                    (speak! fallback))))
              (when (seq tool-calls)
                (tool-dispatch/dispatch-tool-calls dispatch db tool-calls
                  {:on-narrate speak!}))
              (set-history
                (fn [h]
                  (let [h (conj (vec h) user-msg (or message {:role "assistant" :content ""}))]
                    (vec (take-last 20 h))))))))
        (.catch
          (fn [err]
            (js/console.error "AI DM turn failed:" err)
            (dispatch :narration/append
              (str "[AI DM Error] " (.-message err)) "system")))
        (.finally
          (fn [] (set-pending false))))))

;; ---------------------------------------------------------------------------
;; React provider + timer
;; ---------------------------------------------------------------------------

(defui provider
  "Mounts the AI DM state machine and timer loop. Place this inside the
   dispatch and state providers, at the top of the host layout."
  [{:keys [children]}]
  (let [conn                      (uix/use-context state/context)
        dispatch                  (hooks/use-dispatch)
        idb-read                  (idb/use-reader "images")
        [config set-config]       (uix/use-state load-config)
        [pending set-pending]     (uix/use-state false)
        [history set-history]     (uix/use-state [])

        update-config
        (uix/use-callback
          (fn [f]
            (set-config
              (fn [prev]
                (let [next (if (fn? f) (f prev) (merge prev f))]
                  (save-config! next)
                  next)))) [])

        trigger-turn
        (uix/use-callback
          (fn []
            (when-not pending
              (run-turn! conn dispatch config idb-read history set-history set-pending)))
          [conn dispatch config idb-read history pending])

        send-message
        (uix/use-callback
          (fn [text]
            (when-not pending
              (dispatch :narration/append text "host")
              (let [user-msg {:role "user" :content text}
                    history' (vec (take-last 20 (conj history user-msg)))]
                (set-history history')
                (run-turn! conn dispatch config idb-read history' set-history set-pending))))
          [conn dispatch config idb-read history pending])

        ctx-value
        (uix/use-memo
          (fn []
            {:config        config
             :update-config update-config
             :pending       pending
             :history       history
             :trigger-turn  trigger-turn
             :send-message  send-message
             :clear-history #(set-history [])})
          [config update-config pending history trigger-turn send-message])]

    ;; Auto-run timer
    (uix/use-effect
      (fn []
        (when (and (:enabled config) (:auto-approve config))
          (let [id (js/setInterval trigger-turn (:interval-ms config))]
            (fn [] (js/clearInterval id)))))
      [config (:enabled config) (:auto-approve config) (:interval-ms config) trigger-turn])

    ($ context {:value ctx-value}
      children)))
