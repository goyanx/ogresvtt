(ns ogres.app.ai.backends.grok
  (:require [ogres.app.ai.tools :as tools]))

(def ^:private api-url "https://api.x.ai/v1/chat/completions")

(defn chat-completion
  "Sends a chat completion request to the Grok (xAI) API. The API key
   is read from localStorage and never leaves the browser.
   Returns a js/Promise resolving to the parsed response map."
  [{:keys [model messages]}]
  (let [api-key (.getItem js/localStorage "ai-dm-api-key")
        body    (clj->js {:model    model
                          :messages messages
                          :tools    tools/tool-definitions})]
    (when-not (seq api-key)
      (throw (js/Error. "Grok API key not set. Configure it in the AI DM panel.")))
    (-> (js/fetch api-url
          #js {:method  "POST"
               :headers #js {"Content-Type"  "application/json"
                              "Authorization" (str "Bearer " api-key)}
               :body    (js/JSON.stringify body)})
        (.then (fn [resp]
                 (if (.-ok resp)
                   (.json resp)
                   (-> (.text resp)
                       (.then (fn [body]
                                (throw (js/Error.
                                         (str "Grok error " (.-status resp) ": " body)))))))))
        (.then (fn [json]
                 (js->clj json :keywordize-keys true))))))
