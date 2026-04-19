(ns ogres.app.ai.vision
  "Terrain detection via Ollama vision model — single batched request.
   All token crops are sent in one /api/chat call; results returned as JSON.

   The scene background image is stored at its original resolution in IDB.
   Token positions are in scene-space pixels. The SVG renders the image with:
     transform = translate(-origin) scale(const-gs / scene-gs)
   so the inverse (scene → image pixels) is:
     image-x = token-x × (scene-gs / const-gs) + origin-x
     image-y = token-y × (scene-gs / const-gs) + origin-y

   Pull the model first:
     ollama pull qwen3-vl:8b")

;; The fixed rendering unit used by OgresVTT (grid-size constant = 70px).
(def ^:private const-gs 70)

;; ---------------------------------------------------------------------------
;; Canvas crop helpers
;; ---------------------------------------------------------------------------

(defn- crop-to-base64
  "Crops a region of `img` centred on image-space (cx, cy) with source size
   `src-px`, scales it onto a `dst-px × dst-px` canvas, and returns a JPEG
   base64 string (no data-URL prefix).

   Using separate src/dst sizes lets us sample at the correct image resolution
   while keeping the output fed to the vision model at a fixed pixel count."
  [img cx cy src-px dst-px]
  (let [canvas (.createElement js/document "canvas")
        ctx    (.getContext canvas "2d")
        half   (/ src-px 2)
        sx     (max 0 (- cx half))
        sy     (max 0 (- cy half))]
    (set! (.-width canvas) dst-px)
    (set! (.-height canvas) dst-px)
    ;; drawImage(image, sx, sy, sw, sh, dx, dy, dw, dh)
    (.drawImage ctx img sx sy src-px src-px 0 0 dst-px dst-px)
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
  "Sends all token crops in one /api/chat request.
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
     :idb-read      — IDB reader fn (idb/use-reader \"images\")
     :endpoint      — Ollama base URL (default http://localhost:11434)
     :model         — vision model tag (default qwen3-vl:8b)
     :image-hash    — hash of the scene background image
     :scene-gs      — scene's :scene/grid-size in px (default 70)
     :origin-x      — :scene/grid-origin x component (default 0)
     :origin-y      — :scene/grid-origin y component (default 0)
     :crop-squares  — grid squares to crop around each token (default 3)

   Returns a Promise resolving to a map of token-id → terrain-string."
  [tokens {:keys [idb-read endpoint model image-hash scene-gs origin-x origin-y crop-squares]
           :or   {endpoint     "http://localhost:11434"
                  model        "qwen3-vl:8b"
                  scene-gs     const-gs
                  origin-x     0
                  origin-y     0
                  crop-squares 3}}]
  (let [valid-tokens (filterv (fn [{:keys [db/id object/point]}] (and id point)) tokens)
        ;; Crop output canvas size — fixed regardless of scene-gs so the
        ;; vision model always receives the same resolution.
        dst-px       (* crop-squares const-gs)
        ;; Source region size in original image pixels.
        src-px       (* crop-squares scene-gs)
        ;; Scale factor: how many image pixels equal one scene-space pixel.
        img-scale    (/ scene-gs const-gs)]
    (if (empty? valid-tokens)
      (js/Promise.resolve {})
      (-> (idb-read image-hash)
          (.then (fn [record]
                   (if (and record (.-data record))
                     (load-image-from-blob (.-data record))
                     (js/Promise.resolve nil))))
          (.then (fn [img]
                   (if img
                     ;; Convert each token's scene-space position to image-space,
                     ;; crop synchronously, then fire one batched network request.
                     (let [entries (mapv (fn [{:keys [db/id object/point]}]
                                          (let [ix (+ (* (.-x point) img-scale) origin-x)
                                                iy (+ (* (.-y point) img-scale) origin-y)]
                                            {:id  id
                                             :b64 (crop-to-base64 img ix iy src-px dst-px)}))
                                         valid-tokens)]
                       (batch-query-vision-model endpoint model entries))
                     (js/Promise.resolve {}))))
          (.catch (fn [_] {}))))))
