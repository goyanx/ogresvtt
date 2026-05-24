(ns ogres.app.ai.core
  "AI Dungeon Master orchestrator. Manages configuration, the turn timer,
   LLM calls, and tool call dispatch. Runs entirely in the host's browser."
  (:require [clojure.string :as str]
            [datascript.core :as ds]
            [ogres.app.ai.narration :as narration]
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
   :voice-speed   0.95
   :comfy-enabled false
   :comfy-endpoint "http://127.0.0.1:8188"
   :comfy-workflow ""})

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

(defn ^:private latest-chat-ui-message
  "Returns the most recent chat UI message from :root/chat-messages, if any."
  [db]
  (let [root      (ds/entity db [:db/ident :root])
        messages  (:root/chat-messages root)
        latest    (when (seq messages)
                    (last (sort-by :chat/timestamp messages)))
        raw-text  (:chat/text latest)
        text      (when (string? raw-text) (.trim raw-text))]
    (when (seq text)
      {:author    (:chat/author latest)
       :text      text
       :timestamp (:chat/timestamp latest)})))

(defn ^:private current-turn-player?
  "Returns true when initiative is active and the current turn token is a player."
  [db]
  (let [scene      (-> (ds/entity db [:db/ident :user]) :user/camera :camera/scene)
        turn-token (:initiative/turn scene)
        flags      (set (or (:token/flags turn-token) #{}))]
    (contains? flags :player)))

(defn ^:private latest-visible-narration-text
  "Returns the latest visible narration text to use as image prompt seed."
  [db]
  (let [entries (-> (ds/entity db [:db/ident :root]) :root/narration)
        sorted  (sort-by :narration/timestamp (or entries []))]
    (some (fn [entry]
            (when (narration/visible-entry? entry)
              (let [text (some-> (:narration/text entry) str/trim)]
                (when (seq text) text))))
          (reverse sorted))))

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
  [conn dispatch config history set-history set-pending last-chat-ts set-last-chat-ts]
  (set-pending true)
  (let [db          @conn
        game-state  (prompt/serialize-game-state db)
        chat-msg    (latest-chat-ui-message db)
        chat-user-msg
        (when (and chat-msg (not= (:timestamp chat-msg) last-chat-ts))
          {:role "user"
           :content (str "Latest chat UI message from "
                         (or (:author chat-msg) "player")
                         ": "
                         (:text chat-msg))})
        gs          (or (-> (ds/entity db [:db/ident :user])
                            :user/camera :camera/scene :scene/grid-size)
                        grid-size)
        system-msg  {:role "system"
                     :content (prompt/build-system-prompt
                                (:scenario config) game-state gs)}
        user-msg    {:role "user"
                     :content "It is your turn. Review the game state and take appropriate actions."}
        messages    (into [system-msg]
                          (cond-> (vec history)
                            chat-user-msg (conj chat-user-msg)
                            true          (conj user-msg)))]
    (when chat-user-msg
      (set-last-chat-ts (:timestamp chat-msg)))
    (-> (call-backend config messages)
        (.then
          (fn [response]
            (let [choice     (first (:choices response))
                  message    (:message choice)
                  tool-calls (:tool_calls message)
                  validation-errors (:validation_errors response)
                  content    (:content message)
                  speak!     (fn [text]
                               (when (and (:voice-enabled config) (seq text))
                                 (voice/speak! text
                                   {:sidecar-url (:lg-endpoint config)
                                    :voice       (:voice-id config)
                                    :speed       (:voice-speed config)})))]
              (when (and (seq validation-errors)
                         (= (:backend config) :langgraph))
                (dispatch :narration/append
                  (str "[AI DM Validation] "
                       (str/join " | " validation-errors))
                  "system"))
              (when (and (empty? tool-calls)
                         (not (seq validation-errors))
                         (narration/narration-text-visible? content))
                (dispatch :narration/append content "ai")
                (speak! content))
              (when (and (seq tool-calls)
                         (not (seq validation-errors)))
                (let [results (tool-dispatch/dispatch-tool-calls dispatch db tool-calls
                                {:on-narrate speak!})
                      failures (seq (filter (comp not :ok) results))]
                  (when failures
                    (js/console.warn "AI DM tool dispatch failures:" (clj->js failures))
                    (dispatch :narration/append
                      (str "[AI DM Tool Dispatch] "
                           (str/join " | " (map #(or (:reason %) "Unknown dispatch error") failures)))
                      "system"))))
              (set-history
                (fn [h]
                  (let [h (cond-> (vec h)
                            chat-user-msg (conj chat-user-msg))
                        h (conj h user-msg (or message {:role "assistant" :content ""}))]
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
        [image-pending set-image-pending] (uix/use-state false)
        [history set-history]     (uix/use-state [])
        [last-chat-ts set-last-chat-ts] (uix/use-state nil)

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
              (run-turn! conn dispatch config history set-history set-pending
                         last-chat-ts set-last-chat-ts)))
          [conn dispatch config history pending last-chat-ts])

        send-message
        (uix/use-callback
          (fn [text]
            (when-not pending
                (dispatch :narration/append text "host")
                (let [user-msg {:role "user" :content text}
                      history' (vec (take-last 20 (conj history user-msg)))]
                  (set-history history')
                  (run-turn! conn dispatch config history' set-history set-pending
                             last-chat-ts set-last-chat-ts))))
          [conn dispatch config history pending last-chat-ts])

        generate-image
        (uix/use-callback
          (fn [caption]
            (when-not image-pending
              (if-not (:comfy-enabled config)
                (dispatch :narration/append
                  "[AI DM] Narration image generation is disabled in AI DM settings."
                  "system")
                (if (not= (:backend config) :langgraph)
                (dispatch :narration/append
                  "[AI DM] Image generation requires the LangGraph sidecar backend."
                  "system")
                (let [workflow-src (some-> (:comfy-workflow config) str/trim)]
                  (if (empty? workflow-src)
                    (dispatch :narration/append
                      "[AI DM] Add a Comfy workflow JSON in AI Dungeon Master settings first."
                      "system")
                    (try
                      (let [workflow (js->clj (js/JSON.parse workflow-src))
                            caption  (some-> caption str/trim)
                            seed     (or caption
                                         (latest-visible-narration-text @conn)
                                         "fantasy tabletop scene")]
                        (set-image-pending true)
                        (-> (langgraph/comfy-generate
                              {:endpoint       (:lg-endpoint config)
                               :comfy-endpoint (:comfy-endpoint config)
                               :workflow       workflow
                               :prompt-text    seed
                               :prompt-style   (:scenario config)
                               :prompt-model-family "flux"
                               :llm-backend    (name (or (:lg-backend config) :ollama))
                               :llm-endpoint   (:endpoint config)
                               :llm-model      (:model config)})
                            (.then
                              (fn [resp]
                                (let [images (:images resp)
                                      positive-prompt (:positive_prompt resp)]
                                  (if (seq images)
                                    (doseq [img images]
                                      (dispatch :narration/append
                                        (or caption
                                            (str "Generated image: " (:filename img)))
                                        "ai"
                                        {:image-url (:view_url img)
                                         :image-alt (or caption positive-prompt (:filename img))}))
                                    (dispatch :narration/append
                                      "[AI DM] ComfyUI finished but returned no images."
                                      "system")))))
                            (.catch
                              (fn [err]
                                (js/console.error "Comfy generation failed:" err)
                                (dispatch :narration/append
                                  (str "[AI DM Image Error] " (.-message err))
                                  "system")))
                            (.finally
                              (fn [] (set-image-pending false)))))
                      (catch :default err
                        (js/console.error "Invalid Comfy workflow JSON:" err)
                        (dispatch :narration/append
                          (str "[AI DM] Invalid Comfy workflow JSON: " (.-message err))
                          "system")))))))))
          [conn config dispatch image-pending])

        ctx-value
        (uix/use-memo
          (fn []
            {:config        config
             :update-config update-config
             :pending       pending
             :image-pending image-pending
             :history       history
             :trigger-turn  trigger-turn
             :send-message  send-message
             :generate-image generate-image
             :clear-history #(set-history [])})
          [config update-config pending image-pending history trigger-turn send-message generate-image])]

    ;; Auto-run timer
    (uix/use-effect
      (fn []
        (when (and (:enabled config) (:auto-approve config))
          (let [id (js/setInterval
                    (fn []
                      (when-not (current-turn-player? @conn)
                        (trigger-turn)))
                    (:interval-ms config))]
            (fn [] (js/clearInterval id)))))
      [conn config (:enabled config) (:auto-approve config) (:interval-ms config) trigger-turn])

    ($ context {:value ctx-value}
      children)))
