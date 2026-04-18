(ns ogres.app.component.panel-narration
  (:require [ogres.app.ai.core :as ai]
            [ogres.app.component :refer [icon]]
            [ogres.app.hooks :as hooks]
            [uix.core :as uix :refer [defui $]]))

(def ^:private query
  [{:root/narration
    [:db/id
     :narration/text
     :narration/timestamp
     :narration/source]}])

(defui ^:private entry [{:keys [entity]}]
  (let [{:keys [narration/text narration/source narration/timestamp]} entity
        time-str (when timestamp
                   (let [d (js/Date. timestamp)]
                     (str (.getHours d) ":"
                          (.padStart (str (.getMinutes d)) 2 "0"))))]
    ($ :li.narration-entry {:data-source (or source "ai")}
      ($ :.narration-entry-header
        ($ :span.narration-entry-source
          (case source
            "ai"     "AI DM"
            "host"   "Host"
            "system" "System"
            "AI DM"))
        (when time-str
          ($ :span.narration-entry-time time-str)))
      ($ :p.narration-entry-text text))))

(defui ^:memo panel []
  (let [result     (hooks/use-query query [:db/ident :root])
        entries    (:root/narration result)
        sorted     (sort-by :narration/timestamp (or entries []))
        ai-ctx     (uix/use-context ai/context)
        pending    (and (some? ai-ctx) (:pending ai-ctx))
        bottom-ref (uix/use-ref)]
    (uix/use-effect
      (fn []
        (when-let [el (deref bottom-ref)]
          (.scrollIntoView el #js {:behavior "smooth" :block "end"})))
      [(count sorted) pending])
    ($ :.narration
      ($ :header
        ($ :h2 "DM Narration"))
      (if (or (seq sorted) pending)
        ($ :ol.narration-list
          (for [e sorted]
            ($ entry {:key (:db/id e) :entity e}))
          (when pending
            ($ :li.narration-entry {:data-source "ai" :data-pending true}
              ($ :.narration-entry-header
                ($ :span.narration-entry-source "AI DM")
                ($ :span.narration-entry-time "…"))
              ($ :p.narration-entry-text "Thinking…")))
          ($ :li {:ref bottom-ref :style {:height 0 :padding 0 :margin 0 :list-style "none"}}))
        ($ :.narration-empty
          ($ icon {:name "dnd" :size 48})
          ($ :p "No narration yet. Enable the AI DM and run a turn to get started."))))))

(defui ^:memo actions []
  (let [dispatch   (hooks/use-dispatch)
        result     (hooks/use-query [[:user/host :default true]])
        host       (:user/host result)
        ai-ctx     (uix/use-context ai/context)
        ai-enabled (and (some? ai-ctx) (:enabled (:config ai-ctx)))
        pending    (and (some? ai-ctx) (:pending ai-ctx))
        [text set-text] (uix/use-state "")]
    (when host
      ($ :<>
        ($ :form.narration-form
          {:on-submit
           (fn [e]
             (.preventDefault e)
             (when (seq text)
               (if ai-enabled
                 ((:send-message ai-ctx) text)
                 (dispatch :narration/append text "host"))
               (set-text "")))}
          ($ :input.text
            {:type        "text"
             :value       text
             :placeholder (if ai-enabled "Ask the DM..." "Add narration...")
             :disabled    pending
             :on-change   #(set-text (.. % -target -value))})
          ($ :button.button.button-primary
            {:type "submit" :disabled (or (empty? text) pending)}
            (if ai-enabled "Ask" "Send")))
        ($ :button.button.button-neutral
          {:on-click #(dispatch :narration/clear)}
          "Clear")))))
