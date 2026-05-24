(ns ogres.app.provider.state
  (:require [clojure.set :as set]
            [cognitect.transit :as t]
            [datascript.core :as ds]
            [goog.functions :refer [throttle]]
            [ogres.app.const :refer [VERSION]]
            [ogres.app.provider.events :as events]
            [ogres.app.serialize :refer [reader writer]]
            [ogres.app.provider.idb :as idb]
            [ogres.app.vec :as vec]
            [uix.core :as uix :refer [defui $]]))

(def schema
  {:camera/scene      {:db/valueType :db.type/ref}
   :camera/selected   {:db/valueType :db.type/ref :db/cardinality :db.cardinality/many}
   :db/ident          {:db/unique :db.unique/identity}
   :image/hash        {:db/unique :db.unique/identity}
   :image/thumbnail   {:db/valueType :db.type/ref :db/isComponent true}
   :initiative/played {:db/valueType :db.type/ref :db/cardinality :db.cardinality/many}
   :initiative/turn   {:db/valueType :db.type/ref}
   :prop/image        {:db/valueType :db.type/ref}
   :root/scene-images {:db/valueType :db.type/ref :db/cardinality :db.cardinality/many :db/isComponent true}
   :root/scenes       {:db/valueType :db.type/ref :db/cardinality :db.cardinality/many :db/isComponent true}
   :root/session      {:db/valueType :db.type/ref :db/isComponent true}
   :root/chat-messages {:db/valueType :db.type/ref :db/cardinality :db.cardinality/many :db/isComponent true}
   :root/token-images {:db/valueType :db.type/ref :db/cardinality :db.cardinality/many :db/isComponent true}
   :root/narration    {:db/valueType :db.type/ref :db/cardinality :db.cardinality/many :db/isComponent true}
   :root/props-images {:db/valueType :db.type/ref :db/cardinality :db.cardinality/many :db/isComponent true}
   :root/user         {:db/valueType :db.type/ref :db/isComponent true}
   :scene/image       {:db/valueType :db.type/ref}
   :scene/map-external-id {}
   :scene/map-file-path {}
   :scene/map-file-name {}
   :scene/initiative  {:db/valueType :db.type/ref :db/cardinality :db.cardinality/many}
   :scene/masks       {:db/valueType :db.type/ref :db/cardinality :db.cardinality/many :db/isComponent true}
   :scene/trigger-areas {:db/valueType :db.type/ref :db/cardinality :db.cardinality/many :db/isComponent true}
   :scene/shapes      {:db/valueType :db.type/ref :db/cardinality :db.cardinality/many :db/isComponent true}
   :scene/tokens      {:db/valueType :db.type/ref :db/cardinality :db.cardinality/many :db/isComponent true}
   :scene/notes       {:db/valueType :db.type/ref :db/cardinality :db.cardinality/many :db/isComponent true}
   :scene/props       {:db/valueType :db.type/ref :db/cardinality :db.cardinality/many :db/isComponent true}
   :session/conns     {:db/valueType :db.type/ref :db.cardinality :db.cardinality/many :db/isComponent true}
   :session/host      {:db/valueType :db.type/ref}
   :token/image       {:db/valueType :db.type/ref}
   :user/camera       {:db/valueType :db.type/ref}
   :user/cameras      {:db/valueType :db.type/ref :db/cardinality :db.cardinality/many :db/isComponent true}
   :user/dragging     {:db/valueType :db.type/ref :db/cardinality :db.cardinality/many}
   :user/image        {:db/valueType :db.type/ref}
   :user/uuid         {:db/unique :db.unique/identity}})

(defn initial-data [host]
  (ds/db-with
   (ds/empty-db schema)
   [[:db/add -1 :db/ident :root]
    [:db/add -1 :root/release VERSION]
    [:db/add -1 :root/scenes -2]
    [:db/add -1 :root/user -3]
    [:db/add -1 :root/session -5]
    [:db/add -2 :db/empty true]
    [:db/add -3 :db/ident :user]
    [:db/add -3 :user/ready false]
    [:db/add -3 :user/color "red"]
    [:db/add -3 :user/camera -4]
    [:db/add -3 :user/cameras -4]
    [:db/add -3 :user/host host]
    [:db/add -3 :panel/selected :tokens]
    [:db/add -3 :panel/width 640]
    [:db/add -4 :camera/scene -2]
    [:db/add -4 :camera/point vec/zero]
    [:db/add -5 :db/ident :session]]))

(def context (uix/create-context))

(def ^:private trigger-sync-select
  [{:root/scenes
    [:db/id
     :scene/map-external-id
     :scene/map-file-name
     {:scene/shapes
      [:db/id
       :object/type
       :object/point
       [:shape/points :default [vec/zero]]
       :trigger-area/region-key
       [:trigger-area/label :default ""]
       [:trigger-area/context :default ""]
       [:trigger-area/enabled? :default false]]}]}])

(defn ^:private trigger-sync-attrs [report]
  (into #{} (map :a) (:tx-data report)))

(def ^:private trigger-watch-attrs
  #{:trigger-area/region-key
    :trigger-area/label
    :trigger-area/context
    :trigger-area/enabled?
    :shape/points
    :object/point
    :scene/shapes})

(defn ^:private trigger-shape->body [scene shape]
  (let [point (:object/point shape)
        [delta] (:shape/points shape)
        x1 (.-x point)
        y1 (.-y point)
        x2 (+ x1 (.-x delta))
        y2 (+ y1 (.-y delta))
        key (:trigger-area/region-key shape)
        label (or (:trigger-area/label shape) key)
        context (:trigger-area/context shape)
        scene-ext (or (:scene/map-external-id scene)
                      (when-let [name (:scene/map-file-name scene)] (str "map-" name))
                      (str "scene-" (:db/id scene)))]
    {:scene_external_id scene-ext
     :region_key key
     :region_name label
     :geometry_json {:type "bbox"
                     :x1 (min x1 x2)
                     :y1 (min y1 y2)
                     :x2 (max x1 x2)
                     :y2 (max y1 y2)}
     :tags_json {:source "toolbox"
                 :tool "area-trigger"
                 :enabled (:trigger-area/enabled? shape true)
                 :context_text (or context "")}}))

(defn ^:private sidecar-regions-url []
  (let [raw  (.getItem js/localStorage "ai-dm-config")
        conf (if raw
               (try (js/JSON.parse raw) (catch :default _ #js {}))
               #js {})
        base (or (aget conf "lg-endpoint") "http://localhost:8765")]
    (str base "/dm-admin/api/regions/upsert")))

(defn ^:private sync-trigger-shapes! [conn]
  (let [url  (sidecar-regions-url)
        root (ds/pull @conn trigger-sync-select [:db/ident :root])]
    (doseq [scene (:root/scenes root)
            shape (:scene/shapes scene)
            :when (and (= :shape/rect (:object/type shape))
                       (:trigger-area/region-key shape)
                       (:trigger-area/enabled? shape true))]
      (let [body (clj->js (trigger-shape->body scene shape))]
        (-> (js/fetch url
              #js {:method  "POST"
                   :headers #js {"Content-Type" "application/json"}
                   :body    (js/JSON.stringify body)})
            (.catch
             (fn [err]
               (js/console.warn "Failed to sync trigger area to sidecar:" err))))))))

(defui ^:private listeners []
  (let [write (idb/use-writer "images")
        conn (uix/use-context context)
        bootstrap-sync? (uix/use-ref false)]
    ;; Removes the given scene image and its thumbnail from the
    ;; IndexedDB images object store.
    (events/use-subscribe :scene-images/remove
      (uix/use-callback
       (fn [& hashes] (write :delete hashes)) [write]))

    ;; Removes the given token image and its thumbnail from the
    ;; IndexedDB images object store.
    (events/use-subscribe :token-images/remove
      (uix/use-callback
       (fn [& hashes] (write :delete hashes)) [write]))

    ;; Removes the given token images from the IndexedDB images
    ;; object store.
    (events/use-subscribe :token-images/remove-all
      (uix/use-callback
       (fn [hashes] (write :delete hashes)) [write]))

    ;; Syncs trigger area rectangle entities to sidecar SQLite map_regions.
    (events/use-subscribe :tx/commit
      (uix/use-callback
       (fn [report]
         (let [attrs (trigger-sync-attrs report)]
           (when (seq (set/intersection attrs trigger-watch-attrs))
             (sync-trigger-shapes! conn))))
       [conn]))

    ;; One-time bootstrap sync after app state is loaded/restored.
    (uix/use-effect
     (fn []
       (let [key (keyword (str "trigger-bootstrap-sync-" (random-uuid)))
             try-sync
             (fn []
               (when (and (not (.-current bootstrap-sync?))
                          (:user/ready (ds/entity @conn [:db/ident :user])))
                 (set! (.-current bootstrap-sync?) true)
                 (sync-trigger-shapes! conn)))]
         (try-sync)
         (ds/listen! conn key (fn [_] (try-sync)))
         (fn [] (ds/unlisten! conn key))))
     [conn])))

(def ^:private ignored-attrs
  #{:user/host :user/ready :session/status})

(defui ^:private persistence [{:keys [host]}]
  (let [conn  (uix/use-context context)
        read  (idb/use-reader "app")
        write (idb/use-writer "app")]
    ;; Persists the DataScript state to IndexedDB whenever changes
    ;; are made to it.
    (uix/use-effect
     (fn []
       (ds/listen! conn :marshaller
         (throttle
          (fn [{:keys [db-after]}]
            (if (:user/ready (ds/entity db-after [:db/ident :user]))
              (-> db-after
                  (ds/db-with [[:db/retract [:db/ident :session] :session/host]
                               [:db/retract [:db/ident :session] :session/conns]])
                  (ds/filter (fn [_ [_ attr _ _]] (not (contains? ignored-attrs attr))))
                  (ds/datoms :eavt)
                  (as-> datoms (t/write writer datoms))
                  (as-> marshalled #js {:release VERSION :updated (* -1 (.now js/Date)) :data marshalled})
                  (as-> record (write :put [record])))))
          600))
       (fn [] (ds/unlisten! conn :marshaller))) [conn write])

    ;; Reads existing state from IndexedDB, if it exists, and replaces
    ;; the DataScript state with it.
    (uix/use-effect
     (fn []
       (let [tx-data
             [[:db/add [:db/ident :user] :user/ready true]
              [:db/add [:db/ident :user] :user/host host]]]
         (.then (read VERSION)
                (fn [record]
                  (if (nil? record)
                    (ds/transact! conn tx-data)
                    (-> (t/read reader (.-data record))
                        (ds/conn-from-datoms schema)
                        (ds/db)
                        (ds/db-with tx-data)
                        (as-> data (ds/reset-conn! conn data)))))))) ^:lint/disable [])))

(defui provider
  "Provides a DataScript in-memory database to the application and causes
   re-renders when transactions are performed."
  [{:keys [children host] :or {host true}}]
  (let [[conn] (uix/use-state (ds/conn-from-db (initial-data host)))]
    ($ context {:value conn}
      (if host ($ persistence {:host host}))
      ($ listeners)
      children)))

(defn use-query
  ([pattern]
   (use-query pattern [:db/ident :user]))
  ([pattern entity-id]
   (let [conn                   (uix/use-context context)
         get-result             (uix/use-callback #(ds/pull @conn pattern entity-id) ^:lint/disable [])
         [listen-key]           (uix/use-state random-uuid)
         [prev-state set-state] (uix/use-state get-result)]
     (uix/use-effect
      (fn []
        (ds/listen! conn listen-key
          (fn []
            (let [next-state (get-result)]
              (if (not= prev-state next-state)
                (set-state next-state)))))
        (fn []
          (ds/unlisten! conn listen-key))) ^:lint/disable [prev-state])
     prev-state)))
