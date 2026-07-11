(ns ogres.app.ai.backends.langgraph
  "Client for the LangGraph sidecar (ai_dm/main.py).
   Call POST /dm/turn and receive validated tool calls back.
   The sidecar runs: uvicorn ai_dm.main:app --port 8765")

(defn chat-completion
  "Sends a turn request to the LangGraph sidecar.
   Returns a js/Promise that resolves to an OpenAI-compatible response map
   so the existing tool-dispatch pipeline works unchanged."
  [{:keys [endpoint backend model ollama-endpoint messages]}]
  (let [;; Reconstruct scenario + game_state from message history.
        ;; The sidecar expects them split out for its graph nodes.
        system-msg  (first (filter #(= (:role %) "system") messages))
        history     (filterv #(not= (:role %) "system") messages)
        system-text (:content system-msg "")
        ;; Extract scenario and game_state sections from system prompt.
        scenario    (second (re-find #"SCENARIO:\n([\s\S]*?)\n\nRULES:" system-text))
        game-state  (second (re-find #"CURRENT GAME STATE:\n([\s\S]*)$" system-text))
        api-key     (.getItem js/localStorage "ai-dm-api-key")
        url         (str endpoint "/dm/turn")
        body        (clj->js {:backend    (or backend "ollama")
                               :endpoint   (or ollama-endpoint "http://localhost:11434")
                               :model      (or model "")
                               :api_key    (or api-key "")
                               :system_prompt system-text
                               :scenario   (or scenario "")
                               :game_state (or game-state "")
                               :history    history})]
    (-> (js/fetch url
          #js {:method  "POST"
               :headers #js {"Content-Type" "application/json"}
               :body    (js/JSON.stringify body)})
        (.then (fn [resp]
                 (if (.-ok resp)
                   (.json resp)
                   (-> (.text resp)
                       (.then (fn [body]
                                (throw (js/Error.
                                         (str "LangGraph sidecar error "
                                              (.-status resp) ": " body)))))))))
        (.then (fn [json]
                 ;; Wrap sidecar response in OpenAI-compatible envelope
                 ;; so core.cljs tool-dispatch works without changes.
                 (let [data (js->clj json :keywordize-keys true)]
                   {:validation_errors (:validation_errors data [])
                    :retry_count (:retry_count data 0)
                    :choices
                   [{:message
                      {:role       "assistant"
                       :content    (:narration data "")
                       :tool_calls (:tool_calls data [])}}]}))))))

(defn comfy-generate
  "Sends a ComfyUI workflow request via the LangGraph sidecar.
   Returns a js/Promise resolving to {:prompt_id :image_count :images}."
  [{:keys [endpoint comfy-endpoint workflow client-id poll-interval timeout-secs
           prompt-text prompt-style prompt-model-family llm-backend llm-endpoint llm-model
           game-state
           comfy-steps comfy-width comfy-height comfy-batch-size comfy-cfg
           comfy-sampler-name comfy-scheduler]}]
  (let [url  (str endpoint "/dm/comfy/generate")
        api-key (.getItem js/localStorage "ai-dm-api-key")
        body (clj->js {:workflow      workflow
                       :comfy_base_url (or comfy-endpoint "")
                       :client_id     (or client-id "")
                       :poll_interval poll-interval
                       :timeout_secs  timeout-secs
                       :prompt_text   (or prompt-text "")
                       :prompt_style  (or prompt-style "")
                       :prompt_model_family (or prompt-model-family "")
                       :game_state    (or game-state "")
                       :llm_backend   (or llm-backend "")
                       :llm_endpoint  (or llm-endpoint "")
                       :llm_model     (or llm-model "")
                       :api_key       (or api-key "")
                       :comfy_steps   comfy-steps
                       :comfy_width   comfy-width
                       :comfy_height  comfy-height
                       :comfy_batch_size comfy-batch-size
                       :comfy_cfg     comfy-cfg
                       :comfy_sampler_name (or comfy-sampler-name "")
                       :comfy_scheduler (or comfy-scheduler "")})]
    (-> (js/fetch url
          #js {:method  "POST"
               :headers #js {"Content-Type" "application/json"}
               :body    (js/JSON.stringify body)})
        (.then (fn [resp]
                 (if (.-ok resp)
                   (.json resp)
                   (-> (.text resp)
                       (.then (fn [text]
                                (throw (js/Error.
                                         (str "LangGraph sidecar comfy error "
                                              (.-status resp) ": " text)))))))))
        (.then (fn [json] (js->clj json :keywordize-keys true))))))
