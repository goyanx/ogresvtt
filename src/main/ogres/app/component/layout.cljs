(ns ogres.app.component.layout
  (:require [ogres.app.hooks :as hooks]
            [ogres.app.component :refer [icon]]
            [ogres.app.component.panel :as panel]
            [ogres.app.component.scene :refer [scene]]
            [ogres.app.component.scenes :refer [scenes]]
            [ogres.app.component.toolbar :refer [toolbar]]
            [ogres.app.component.players :refer [players]]
            [ogres.app.provider.window :as window]
            [uix.core :as uix :refer [defui $]]))

(def ^:private query
  [[:user/ready :default false]
   [:user/host :default true]
   [:panel/expanded :default true]
   [:panel/width :default 640]
   [:session/status :default :none]])

(def ^:private panel-min-width 360)
(def ^:private panel-max-width 1100)
(def ^:private panel-width-default 640)
(def ^:private panel-width-legacy-default 520)
(def ^:private panel-width-migration-key "panel-width-migrated-v1")

(defn ^:private clamp [n min max]
  (max min (min max n)))

(defui ^:memo layout []
  (let [dispatch (hooks/use-dispatch)
        result (hooks/use-query query)
        {host        :user/host
         ready       :user/ready
         status      :session/status
         expanded    :panel/expanded
         panel-width :panel/width} result
        panel-width (or panel-width panel-width-default)
        node (uix/use-context window/context)
        [drag-state set-drag-state] (uix/use-state nil)
        start-drag
        (uix/use-callback
         (fn [event]
           (.preventDefault event)
           (set-drag-state {:start-x (.-clientX event)
                            :start-width panel-width}))
         [panel-width])]
    (uix/use-effect
     (fn []
       (when (and (not expanded) (some? drag-state))
         (set-drag-state nil)))
     [expanded drag-state])
    (uix/use-effect
     (fn []
       (when (and (= panel-width panel-width-legacy-default)
                  (not (.getItem js/localStorage panel-width-migration-key)))
         (dispatch :panel/change-width panel-width-default)
         (.setItem js/localStorage panel-width-migration-key "1")))
     [panel-width dispatch])
    (uix/use-effect
     (fn []
       (if (nil? drag-state)
         (do
           (.remove (.-classList (.-body js/document)) "layout-resizing")
           nil)
         (let [{:keys [start-x start-width]} drag-state
               on-move
               (fn [event]
                 (let [delta (- start-x (.-clientX event))
                       max-width (clamp (- (or (.-innerWidth js/window) panel-max-width) 280)
                                        panel-min-width panel-max-width)
                       next-width (-> (+ start-width delta)
                                      (clamp panel-min-width max-width)
                                      js/Math.round)]
                   (dispatch :panel/change-width next-width)))
               on-up
               (fn [_]
                 (set-drag-state nil))]
           (.add (.-classList (.-body js/document)) "layout-resizing")
           (.addEventListener js/window "mousemove" on-move)
           (.addEventListener js/window "mouseup" on-up)
           (.addEventListener js/window "blur" on-up)
           (fn []
             (.removeEventListener js/window "mousemove" on-move)
             (.removeEventListener js/window "mouseup" on-up)
             (.removeEventListener js/window "blur" on-up)
             (.remove (.-classList (.-body js/document)) "layout-resizing")))))
     [drag-state dispatch])
    (let [layout-body
          (fn [user]
            ($ :.layout
              {:data-user user
               :data-expanded expanded
               :style {"--panel-side-width" (str panel-width "px")}}
              (when host
                ($ :.layout-scenes  ($ scenes)))
              ($ :.layout-scene {:ref node}
                ($ scene))
              ($ :.layout-toolbar ($ toolbar))
              ($ :.layout-players ($ players))
              ($ :.layout-panel ($ panel/panel))
              (when expanded
                ($ :button.layout-resizer
                  {:type "button"
                   :title "Resize side panel"
                   :aria-label "Resize side panel"
                   :on-mouse-down start-drag}))))]
      (cond (and host ready)
            (layout-body "host")
            (and (not host) (= status :connected) ready)
            (layout-body "conn")
            (and (not host) (= status :disconnected))
            ($ :.layout-error
              ($ :.layout-error-content
                ($ :div {:style {:margin-top 4 :color "hsl(6, 73%, 60%)"}}
                  ($ icon {:name "exclamation-triangle-fill"}))
                ($ :div
                  ($ :div {:style {:font-size 20 :line-height 1}}
                    "Connection to the room could not be started or it was interrupted.")
                  ($ :div {:style {:margin-top 16}}
                    "Some possible reasons this might have happened:")
                  ($ :ul {:style {:margin "0.25rem 1.2rem 1rem 1.2rem" :list-style-type "disc"}}
                    ($ :li "The room you were in was closed by the host")
                    ($ :li "The room was automatically closed due to inactivity")
                    ($ :li "The room you tried to join does not exist")
                    ($ :li "The host is using a map image that exceeds the server limit (10MB)")
                    ($ :li "The server is undergoing maintenance"))
                  ($ :div "Stay here and we'll keep trying to establish your connection every five seconds.")
                  ($ :nav {:style {:margin-top 16 :color "var(--color-danger-500)"}}
                    ($ :ul {:style {:display "flex" :gap 16}}
                      ($ :li ($ :a {:href "/"} "Home"))
                      ($ :li ($ :a {:href "https://github.com/samcf/ogres/wiki"} "Wiki"))
                      ($ :li ($ :a {:href "https://github.com/samcf/ogres/discussions"} "Support")))))))))))
