(ns ogres.app.ai.vision
  "Terrain detection via Ollama vision model — single batched request.
   All token crops are sent in one /api/chat call; results are returned
   as a JSON array so there is only one model inference per turn.

   Pull the model first:
     ollama pull qwen3-vl:8b")

;; ---------------------------------------------------------------------------
;; Canvas crop helpers
;; ---------------------------------------------------------------------------

(defn- crop-to-base64
  "Draws a square crop of `img` centred on (cx, cy) onto an offscreen canvas
   and returns a JPEG base64 string (no data-URL prefix)."
  [img cx cy crop-px]
  (let [canvas (.createElement js/document "canvas")
        ctx    (.getContext canvas "2d")
        half   (/ crop-px 2)
        sx     (max 0 (- cx half))
        sy     (max 0 (- cy half))]
    (set! (.-width canvas) crop-px)
    (set! (.-height canvas) crop-px)
    (.drawImage ctx img sx sy crop-px crop-px 0 0 crop-px crop-px)
    (-> (.toDataURL canvas "image/jpeg" 0.65)
        (.replace "data:image/jpeg;base64," ""))))

(defn- load-image-from-blob [blob]
  (js/Promise.
    (fn [resolve reject]
      (let [url (js/URL.createObjectURL blob)
            img (js/Image.)]
        (set! (.-onload  img) (fn [] (js/URL.revokeObjectURL url) (resolve img)))
        (set! (.-onerror img) (fn [e] (js/URL.revokeObjectURL url) (reject e)))
        (set! (.-src img) url)))))

;; ---------------------------------------------------------------------------
;; Batched Ollama vision call
;; ---------------------------------------------------------------------------

(defn- batch-query-vision-model
  "Sends all token crops in a single /api/chat request.
   `token-entries` is a vector of {:id int :b64 string}.
   Returns a Promise resolving to a map of token-id → terrain string."
  [endpoint model token-entries]
  (let [ids    (mapv :id token-entries)
        images (mapv :b64 token-entries)
        n      (count ids)
        prompt (str "You are analysing " n " small crops from a fantasy tabletop RPG map. "
                    "The images are in order — one crop per token. "
                    "For each image describe ONLY the terrain/surface type in 2-4 words. "
                    "Do NOT mention tokens, figures, or game pieces. "
                    "Respond with JSON only, no other text: "
                    "{\"terrains\":[\"terrain for image 1\",\"terrain for image 2\",...]}")
        url    (str endpoint "/api/chat")
        body   (clj->js {:model    model
                         :stream   false
                         :format   "json"
                         :messages [{:role    "user"
                                     :content prompt
                                     :images  images}]})]
    (-> (js/fetch url
          #js {:method  "POST"
               :headers #js {"Content-Type" "application/json"}
               :body    (js/JSON.stringify body)})
        (.then (fn [resp]
                 (if (.-ok resp) (.json resp) (js/Promise.resolve nil))))
        (.then (fn [json]
                 (when json
                   (let [text (-> (js->clj json :keywordize-keys true)
                                  (get-in [:message :content])
                                  (some-> .trim))]
                     (try
                       (let [parsed   (js->clj (js/JSON.parse text) :keywordize-keys true)
                             terrains (or (:terrains parsed) [])]
                         (into {}
                           (keep-indexed
                             (fn [i terrain]
                               (when-let [id (nth ids i nil)]
                                 [id terrain]))
                             terrains)))
                       (catch :default _ {}))))))
        (.catch (fn [_] {})))))

;; ---------------------------------------------------------------------------
;; Public API
;; ---------------------------------------------------------------------------

(defn detect-all-terrain!
  "Detects terrain for every token in `tokens` using a single batched vision
   request. The scene image is loaded once; all crops are sent together.

   opts:
     :idb-read      — IDB reader fn returned by (idb/use-reader \"images\")
     :endpoint      — Ollama base URL (default http://localhost:11434)
     :model         — vision model tag (default qwen3-vl:8b)
     :image-hash    — hash of the scene background image
     :grid-size     — pixels per grid square (default 70)
     :crop-squares  — how many squares to crop around each token (default 3)

   Returns a Promise resolving to a map of token-id → terrain-string."
  [tokens {:keys [idb-read endpoint model image-hash grid-size crop-squares]
           :or   {endpoint     "http://localhost:11434"
                  model        "qwen3-vl:8b"
                  grid-size    70
                  crop-squares 3}}]
  (let [valid-tokens (filterv (fn [{:keys [db/id object/point]}] (and id point)) tokens)
        crop-px      (* crop-squares grid-size)]
    (if (empty? valid-tokens)
      (js/Promise.resolve {})
      (-> (idb-read image-hash)
          (.then (fn [record]
                   (if (and record (.-data record))
                     (load-image-from-blob (.-data record))
                     (js/Promise.resolve nil))))
          (.then (fn [img]
                   (if img
                     ;; Crop all tokens synchronously (fast canvas ops), then one network call
                     (let [entries (mapv (fn [{:keys [db/id object/point]}]
                                          {:id  id
                                           :b64 (crop-to-base64 img (.-x point) (.-y point) crop-px)})
                                         valid-tokens)]
                       (batch-query-vision-model endpoint model entries))
                     (js/Promise.resolve {}))))
          (.catch (fn [_] {}))))))
