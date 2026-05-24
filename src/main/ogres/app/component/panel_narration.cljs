(ns ogres.app.component.panel-narration
  (:require [ogres.app.ai.core :as ai]
            [ogres.app.ai.narration :as narration]
            [ogres.app.component :refer [icon]]
            [ogres.app.hooks :as hooks]
            [uix.core :as uix :refer [defui $]]))

(def ^:private query
  [{:root/narration
    [:db/id
     :narration/text
     :narration/timestamp
     :narration/source
     :narration/image-url
     :narration/image-alt]}])

(def ^:private thinking-labels
  ["Reading scene state"
   "Checking initiative order"
   "Selecting current combatant"
   "Checking token positions"
   "Validating range and line of sight"
   "Planning next actions"
   "Composing narrative response"])

(defn ^:private use-thinking-status
  [pending]
  (let [[elapsed set-elapsed] (uix/use-state 0)]
    (uix/use-effect
      (fn []
        (if pending
          (let [id (js/setInterval #(set-elapsed inc) 1000)]
            (fn [] (js/clearInterval id)))
          (set-elapsed 0)))
      [pending])
    (let [idx (mod (quot elapsed 4) (count thinking-labels))
          label (nth thinking-labels idx)]
      {:elapsed elapsed
       :label label})))

(defui ^:private entry [{:keys [entity]}]
  (let [{:keys [narration/text narration/source narration/timestamp
                narration/image-url narration/image-alt]} entity
        time-str (when timestamp
                   (let [d (js/Date. timestamp)]
                     (str (.getHours d) ":"
                          (.padStart (str (.getMinutes d)) 2 "0")
                          ":"
                          (.padStart (str (.getSeconds d)) 2 "0"))))]
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
      (when (seq text)
        ($ :p.narration-entry-text
          {:style {:userSelect "text"
                   :WebkitUserSelect "text"}}
          text))
      (when (seq image-url)
        ($ :figure.narration-entry-figure
          ($ :img.narration-entry-image
            {:src image-url
             :alt (or image-alt "Generated narration art")
             :loading "lazy"}))))))

(defui ^:memo panel []
  (let [result     (hooks/use-query query [:db/ident :root])
        entries    (:root/narration result)
        sorted     (sort-by :narration/timestamp (or entries []))
        visible    (filter narration/visible-entry? sorted)
        ai-ctx     (uix/use-context ai/context)
        pending    (and (some? ai-ctx) (:pending ai-ctx))
        {thinking-label :label thinking-elapsed :elapsed} (use-thinking-status pending)
        bottom-ref (uix/use-ref)]
    (uix/use-effect
      (fn []
        (when-let [el (deref bottom-ref)]
          (.scrollIntoView el #js {:behavior "smooth" :block "end"})))
      [(count visible) pending])
    ($ :.narration
      {:style {:userSelect "text"
               :WebkitUserSelect "text"}}
      ($ :header
        ($ :h2 "DM Narration"))
      (if (or (seq visible) pending)
        ($ :ol.narration-list
          (for [e visible]
            ($ entry {:key (:db/id e) :entity e}))
          (when pending
            ($ :li.narration-entry {:data-source "ai" :data-pending true}
              ($ :.narration-entry-header
                ($ :span.narration-entry-source "AI DM")
                ($ :span.narration-entry-time "…"))
              ($ :p.narration-entry-text
                (str thinking-label " (" thinking-elapsed "s)…"))))
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
        comfy-enabled (and ai-enabled (:comfy-enabled (:config ai-ctx)))
        langgraph? (and ai-enabled (= :langgraph (:backend (:config ai-ctx))))
        pending    (and (some? ai-ctx) (:pending ai-ctx))
        image-pending (and (some? ai-ctx) (:image-pending ai-ctx))
        [text set-text] (uix/use-state "")
        [image-caption set-image-caption] (uix/use-state "")]
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
        (when (and ai-enabled comfy-enabled)
          ($ :form.narration-form
            {:on-submit
             (fn [e]
               (.preventDefault e)
               (when (and (fn? (:generate-image ai-ctx))
                          langgraph?
                          (not pending)
                          (not image-pending))
                 ((:generate-image ai-ctx) image-caption)))}
            ($ :input.text
              {:type "text"
               :value image-caption
               :placeholder (if langgraph?
                              "Art prompt seed (optional)..."
                              "Switch backend to LangGraph for ComfyUI")
               :disabled (or pending image-pending (not langgraph?))
               :on-change #(set-image-caption (.. % -target -value))})
            ($ :button.button.button-neutral
              {:type "submit"
               :disabled (or pending image-pending (not langgraph?))}
              (if image-pending "Rendering..." "Generate art"))))
        (when (and ai-enabled (not comfy-enabled))
          ($ :p
            {:style {:fontSize "12px"
                     :color "var(--color-black-500)"
                     :margin "2px 0 4px"}}
            "Enable narration images in the AI Dungeon Master panel to use Generate art."))
        ($ :button.button.button-neutral
          {:disabled image-pending
           :on-click #(dispatch :narration/clear)}
          "Clear")))))
