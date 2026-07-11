(ns ogres.app.component.panel-chat
  (:require [ogres.app.hooks :as hooks]
            [uix.core :as uix :refer [defui $]]))

(def ^:private query
  [{:root/chat-messages
    [:db/id :chat/text :chat/author :chat/color :chat/timestamp]}
   {:root/user [:user/label :user/color]}])

(defn ^:private format-time [timestamp]
  (-> (js/Date. timestamp)
      (.toLocaleTimeString [] #js {:hour "2-digit" :minute "2-digit"})))

(defui ^:memo panel []
  (let [result   (hooks/use-query query [:db/ident :root])
        messages (sort-by :chat/timestamp (:root/chat-messages result))
        list-ref (uix/use-ref nil)]
    (uix/use-effect
     (fn []
       (when-let [el (.-current list-ref)]
         (set! (.-scrollTop el) (.-scrollHeight el))))
     [messages])
    ($ :.chat-messages
      {:ref list-ref}
      (if (empty? messages)
        ($ :.chat-empty "No messages yet.")
        (for [{:keys [db/id chat/text chat/author chat/color chat/timestamp]} messages]
          ($ :.chat-message {:key id}
            ($ :.chat-message-header
              {:data-color color}
              ($ :.chat-message-dot)
              ($ :span.chat-message-author author)
              ($ :span.chat-message-time (format-time timestamp)))
            ($ :.chat-message-body
              {:data-color color}
              ($ :p.chat-message-text text))))))))

(defui ^:memo actions []
  (let [[text set-text] (uix/use-state "")
        dispatch (hooks/use-dispatch)
        send!
        (uix/use-callback
         (fn []
           (let [trimmed (.trim text)]
             (when (seq trimmed)
               (dispatch :chat/send trimmed)
               (set-text "")))) [text dispatch])]
    ($ :.chat-input
      ($ :input.chat-input-field
        {:type        "text"
         :placeholder "Say something..."
         :value       text
         :on-change   #(set-text (.. % -target -value))
         :on-key-down (fn [e] (when (= (.-key e) "Enter") (send!)))})
      ($ :button.button.button-primary
        {:type     "button"
         :disabled (empty? (.trim text))
         :on-click send!}
        "Send"))))
