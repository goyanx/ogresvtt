(ns ogres.app.ai.backends.ollama
  (:require [ogres.app.ai.tools :as tools]))

(defn chat-completion
  "Sends a chat completion request to an Ollama instance using the
   OpenAI-compatible endpoint. Returns a js/Promise resolving to
   the parsed response map."
  [{:keys [endpoint model max-output-tokens messages]}]
  (let [url  (str endpoint "/v1/chat/completions")
        body (clj->js
               (cond-> {:model    model
                        :messages messages
                        :tools    tools/tool-definitions
                        :stream   false}
                 (and (number? max-output-tokens) (pos? max-output-tokens))
                 (assoc :max_tokens max-output-tokens)))]
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
                                         (str "Ollama error " (.-status resp) ": " body)))))))))
        (.then (fn [json]
                 (js->clj json :keywordize-keys true))))))
