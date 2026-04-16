(ns ogres.app.ai.core
  "AI Dungeon Master orchestrator. Manages configuration, the turn timer,
   LLM calls, and tool call dispatch. Runs entirely in the host's browser."
  (:require [datascript.core :as ds]
            [ogres.app.ai.prompt :as prompt]
            [ogres.app.ai.tool-dispatch :as tool-dispatch]
            [ogres.app.ai.backends.ollama :as ollama]
            [ogres.app.ai.backends.grok :as grok]
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
   :endpoint     "http://localhost:11434"
   :model        "llama3.1"
   :scenario     ""
   :auto-approve true
   :interval-ms  15000})

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
    :ollama (ollama/chat-completion
              {:endpoint (:endpoint config)
               :model    (:model config)
               :messages messages})
    :grok   (grok/chat-completion
              {:model    (:model config)
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
                  content    (:content message)]
              ;; If the model returned plain text content (no narrate tool call),
              ;; treat it as narration.
              (when (and (seq content) (empty? tool-calls))
                (dispatch :narration/append content "ai"))
              ;; Dispatch each tool call.
              (when (seq tool-calls)
                (tool-dispatch/dispatch-tool-calls dispatch db tool-calls))
              ;; Append to conversation history (keep last 20 messages).
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

        ctx-value
        (uix/use-memo
          (fn []
            {:config        config
             :update-config update-config
             :pending       pending
             :history       history
             :trigger-turn  trigger-turn
             :clear-history #(set-history [])})
          [config update-config pending history trigger-turn])]

    ;; Auto-run timer
    (uix/use-effect
      (fn []
        (when (and (:enabled config) (:auto-approve config))
          (let [id (js/setInterval trigger-turn (:interval-ms config))]
            (fn [] (js/clearInterval id)))))
      [(:enabled config) (:auto-approve config) (:interval-ms config) trigger-turn])

    ($ context {:value ctx-value}
      children)))
