(ns ogres.app.ai.core
  "AI Dungeon Master orchestrator. Manages configuration, the turn timer,
   LLM calls, and tool call dispatch. Runs entirely in the host's browser."
  (:require [datascript.core :as ds]
            [ogres.app.ai.prompt :as prompt]
            [ogres.app.ai.tool-dispatch :as tool-dispatch]
            [ogres.app.ai.backends.ollama :as ollama]
            [ogres.app.ai.backends.grok :as grok]
            [ogres.app.ai.backends.langgraph :as langgraph]
            [ogres.app.ai.voice :as voice]
            [ogres.app.const :refer [grid-size]]
            [ogres.app.hooks :as hooks]
            [ogres.app.provider.state :as state]
            [uix.core :as uix :refer [defui $]]))

;; ---------------------------------------------------------------------------
;; Configuration (persisted to localStorage)
;; ---------------------------------------------------------------------------

(def default-config
  {:enabled      false
   :backend      :ollama
   :lg-backend   :ollama
   :endpoint     "http://localhost:11434"
   :model        "qwen2.5:14b-instruct-q4_K_M"
   :lg-endpoint  "http://localhost:8765"
   :scenario     ""
   :auto-approve true
   :interval-ms  15000
   :voice-enabled false
   :voice-id      "bm_george"
   :voice-speed   0.95})

(defn load-config
  "Loads AI DM configuration from localStorage, merging with defaults."
  []
  (if-let [raw (.getItem js/localStorage "ai-dm-config")]
    (try
      (let [parsed (js->clj (js/JSON.parse raw) :keywordize-keys true)]
        (merge default-config
               (-> parsed
                   (update :backend #(if (string? %) (keyword %) %))
                   (update :lg-backend #(if (string? %) (keyword %) %)))))
      (catch :default _ default-config))
    default-config))

(defn save-config!
  "Persists AI DM configuration to localStorage."
  [config]
  (.setItem js/localStorage "ai-dm-config"
    (js/JSON.stringify
      (clj->js
        (-> config
            (update :backend #(if (some? %) (name %) %))
            (update :lg-backend #(if (some? %) (name %) %)))))))

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
                 {:endpoint (:lg-endpoint config)
                  :backend  (name (or (:lg-backend config) :ollama))
                  :model    (:model config)
                  :ollama-endpoint (:endpoint config)
                  :messages messages})
    (js/Promise.reject (js/Error. (str "Unknown backend: " (:backend config))))))

;; ---------------------------------------------------------------------------
;; Turn execution
;; ---------------------------------------------------------------------------

(defn run-turn!
  "Executes a single AI DM turn: serialize state, call LLM, dispatch tool calls."
  [conn dispatch config history set-history set-pending]
  (set-pending true)
  (let [db          @conn
        game-state  (prompt/serialize-game-state db)
        gs          (or (-> (ds/entity db [:db/ident :user])
                            :user/camera :camera/scene :scene/grid-size)
                        grid-size)
        system-msg  {:role "system"
                     :content (prompt/build-system-prompt
                                (:scenario config) game-state gs)}
        user-msg    {:role "user"
                     :content "It is your turn. Review the game state and take appropriate actions."}
        messages    (into [system-msg] (conj (vec history) user-msg))]
    (-> (call-backend config messages)
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
                (dispatch :narration/append content "ai")
                (speak! content))
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
              (run-turn! conn dispatch config history set-history set-pending)))
          [conn dispatch config history pending])

        send-message
        (uix/use-callback
          (fn [text]
            (when-not pending
              (dispatch :narration/append text "host")
              (let [user-msg {:role "user" :content text}
                    history' (vec (take-last 20 (conj history user-msg)))]
                (set-history history')
                (run-turn! conn dispatch config history' set-history set-pending))))
          [conn dispatch config history pending])

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
