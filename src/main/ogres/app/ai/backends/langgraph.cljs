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
                   {:choices
                    [{:message
                      {:role       "assistant"
                       :content    (:narration data "")
                       :tool_calls (:tool_calls data [])}}]}))))))
