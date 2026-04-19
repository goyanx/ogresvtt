(ns ogres.app.ai.vision
  "Terrain detection via Ollama vision model.
   Crops the scene map image around a token position, encodes it as base64,
   and asks the vision model what terrain the token is standing on.

   Pull the model first:
     ollama pull qwen2.5-vl:7b")

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
    ;; drawImage(image, sx, sy, sw, sh, dx, dy, dw, dh)
    (.drawImage ctx img sx sy crop-px crop-px 0 0 crop-px crop-px)
    (-> (.toDataURL canvas "image/jpeg" 0.75)
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
;; Ollama vision call
;; ---------------------------------------------------------------------------

(def ^:private terrain-prompt
  "You are analysing a small crop from a fantasy tabletop RPG map.
Describe ONLY the terrain/surface type in 2-5 words.
Examples: 'stone cave floor', 'dungeon wall', 'underground river',
'wooden bridge', 'forest path', 'open grassland', 'rocky outcrop',
'sand', 'shallow water', 'dark corridor'.
Do NOT mention any tokens, figures, or game pieces.")

(defn- query-vision-model
  "Posts a base64 image crop to the Ollama /api/chat vision endpoint.
   Returns a Promise resolving to the terrain description string."
  [endpoint model base64-img]
  (let [url  (str endpoint "/api/chat")
        body (clj->js {:model    model
                       :stream   false
                       :messages [{:role    "user"
                                   :content terrain-prompt
                                   :images  [base64-img]}]})]
    (-> (js/fetch url
          #js {:method  "POST"
               :headers #js {"Content-Type" "application/json"}
               :body    (js/JSON.stringify body)})
        (.then (fn [resp]
                 (if (.-ok resp)
                   (.json resp)
                   (js/Promise.resolve nil))))
        (.then (fn [json]
                 (when json
                   (-> (js->clj json :keywordize-keys true)
                       (get-in [:message :content])
                       (some-> .trim)))))
        (.catch (fn [_] nil)))))

;; ---------------------------------------------------------------------------
;; Public API
;; ---------------------------------------------------------------------------

(defn detect-terrain!
  "Detects the terrain under a single token.

   opts:
     :idb-read      — IDB reader fn returned by (idb/use-reader \"images\")
     :endpoint      — Ollama base URL (default http://localhost:11434)
     :model         — vision model tag (default qwen2.5-vl:7b)
     :image-hash    — hash of the scene background image
     :token-x       — token x in scene-space pixels
     :token-y       — token y in scene-space pixels
     :grid-size     — pixels per grid square (default 70)
     :crop-squares  — how many squares to crop around token (default 3)

   Returns a Promise resolving to a terrain string or nil on failure."
  [{:keys [idb-read endpoint model image-hash token-x token-y grid-size crop-squares]
    :or   {endpoint     "http://localhost:11434"
           model        "qwen2.5-vl:7b"
           grid-size    70
           crop-squares 3}}]
  (let [crop-px (* crop-squares grid-size)]
    (-> (idb-read image-hash)
        (.then (fn [record]
                 (if (and record (.-data record))
                   (load-image-from-blob (.-data record))
                   (js/Promise.resolve nil))))
        (.then (fn [img]
                 (when img
                   (let [b64 (crop-to-base64 img token-x token-y crop-px)]
                     (query-vision-model endpoint model b64)))))
        (.catch (fn [_] nil)))))

(defn detect-all-terrain!
  "Detects terrain for every token in `tokens` concurrently.
   Returns a Promise resolving to a map of token-id → terrain-string."
  [tokens opts]
  (let [promises
        (for [{:keys [db/id object/point]} tokens
              :when (and id point)]
          (-> (detect-terrain!
                (assoc opts
                  :token-x (.-x point)
                  :token-y (.-y point)))
              (.then (fn [terrain] [id (or terrain "unknown")]))))]
    (-> (js/Promise.all (clj->js promises))
        (.then (fn [results]
                 (into {} (map vec (js->clj results))))))))
