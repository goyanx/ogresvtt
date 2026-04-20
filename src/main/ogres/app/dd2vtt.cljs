(ns ogres.app.dd2vtt
  "Parser for Universal VTT map files (.dd2vtt / .uvtt / .df2vtt).

   These files are JSON blobs containing a base64-encoded PNG image plus
   explicit wall, door, and light geometry. The format is produced by
   Dungeondraft, Dungeon Alchemist, Dungeon Fog, and other map tools.

   Wall segments and door bounds in a UVTT file are expressed in grid-cell
   units (1.0 = one cell). OgresVTT's internal coordinate system uses
   70 pixels per cell. Parsed geometry is converted to that pixel space
   so it can be compared directly against token coordinates."
  (:require [ogres.app.const :refer [grid-size]]))

(def ^:private supported-extensions
  #{"dd2vtt" "uvtt" "df2vtt"})

(defn universal-vtt-file?
  "Returns true if the File's name ends in a known UVTT extension."
  [^js/File file]
  (let [name (.-name file)
        dot  (.lastIndexOf name ".")]
    (and (pos? dot)
         (contains? supported-extensions
                    (.toLowerCase (.substring name (inc dot)))))))

(defn ^:private base-name
  "Returns the filename without its extension."
  [^js/File file]
  (let [n (.-name file)
        i (.lastIndexOf n ".")]
    (if (pos? i) (.substring n 0 i) n)))

(defn ^:private b64->blob
  "Decodes a base64-encoded string into a Blob of the given MIME type."
  [^String b64 ^String mime]
  (let [binary (js/atob b64)
        len    (.-length binary)
        bytes  (js/Uint8Array. len)]
    (dotimes [i len]
      (aset bytes i (.charCodeAt binary i)))
    (js/Blob. #js [bytes] #js {:type mime})))

(defn ^:private segments-from-polyline
  "Converts a UVTT polyline (sequence of {x y} points) into a list of
   [x1 y1 x2 y2] segments in internal scene pixel space. `scale` is the
   multiplier from grid-cells to internal pixels (i.e. grid-size)."
  [points scale]
  (let [pts (vec points)]
    (for [i (range (dec (count pts)))
          :let [a (nth pts i)
                b (nth pts (inc i))]]
      [(* scale (.-x a)) (* scale (.-y a))
       (* scale (.-x b)) (* scale (.-y b))])))

(defn ^:private parse-walls
  "Extracts wall segments from the `line_of_sight` array. Each entry is
   a polyline; we explode it into individual line segments."
  [^js raw scale]
  (let [lines (or (.-line_of_sight raw) #js [])]
    (into []
          (mapcat (fn [poly] (segments-from-polyline (array-seq poly) scale)))
          (array-seq lines))))

(defn ^:private parse-objects-walls
  "Extracts the additional line-of-sight blockers created by objects
   placed on the map (furniture etc.)."
  [^js raw scale]
  (let [lines (or (.-objects_line_of_sight raw) #js [])]
    (into []
          (mapcat (fn [poly] (segments-from-polyline (array-seq poly) scale)))
          (array-seq lines))))

(defn ^:private parse-doors
  "Extracts doors (`portals`). Each portal carries a bounds polyline and
   a `closed` flag. We represent each as a map with segments plus the
   closed state."
  [^js raw scale]
  (let [portals (or (.-portals raw) #js [])]
    (into []
          (map (fn [^js p]
                 {:closed   (if (false? (.-closed p)) false true)
                  :segments (vec (segments-from-polyline
                                  (array-seq (or (.-bounds p) #js []))
                                  scale))}))
          (array-seq portals))))

(defn ^:private image-blob-from-uvtt
  "Extracts the base64 image from a parsed UVTT object and returns a Blob.
   Most tools use the `image` key; some older exports use `imageUrl`."
  [^js raw]
  (let [b64 (or (.-image raw) (.-imageUrl raw))]
    (when (string? b64)
      ;; Tolerate a leading data-URL prefix if present.
      (let [clean (if (>= (.indexOf b64 ",") 0)
                    (.substring b64 (inc (.indexOf b64 ",")))
                    b64)]
        (b64->blob clean "image/png")))))

(defn ^:private image-file-from-blob
  "Wraps a Blob in a File so it can flow through the existing image
   pipeline, which expects a named File."
  [blob filename]
  (js/File. #js [blob] filename #js {:type "image/png"}))

(defn parse-text
  "Parses UVTT JSON text and returns a map:
     :image-file   js/File holding the decoded PNG
     :walls        vector of [x1 y1 x2 y2] segments in pixel space
     :doors        vector of {:closed bool :segments [...]}
     :grid-size    pixels per cell in internal space (always grid-size)
     :map-cells-x  map width in grid cells (or nil)
     :map-cells-y  map height in grid cells (or nil)"
  [^String json-text filename]
  (let [raw  (.parse js/JSON json-text)
        ;; UVTT coords are in grid-cell units; convert to internal pixels.
        scale grid-size
        blob (image-blob-from-uvtt raw)
        file (some-> blob (image-file-from-blob filename))
        res  (.-resolution raw)
        sz   (when res (.-map_size res))]
    {:image-file  file
     :walls       (into (parse-walls raw scale)
                        (parse-objects-walls raw scale))
     :doors       (parse-doors raw scale)
     :grid-size   grid-size
     :map-cells-x (when sz (.-x sz))
     :map-cells-y (when sz (.-y sz))}))

(defn parse-file
  "Reads a UVTT File and returns a Promise resolving to a parsed map
   (see `parse-text` for shape)."
  [^js/File file]
  (-> (.text file)
      (.then (fn [text]
               (parse-text text (str (base-name file) ".png"))))))
