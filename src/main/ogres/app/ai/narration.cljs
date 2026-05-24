(ns ogres.app.ai.narration
  (:require [clojure.string :as str]))

(def ^:private hidden-sources
  #{"system" "app"})

(def ^:private meta-pattern
  #"(?is)(```|\"name\"\s*:|\"arguments\"\s*:|tool_calls?|\[ai dm error\]|\bjson\b|^\s*step\s*\d+[:\-])")

(defn visible-source?
  [source]
  (not (contains? hidden-sources (or source ""))))

(defn narration-text-visible?
  [text]
  (let [s (some-> text str/trim)]
    (and (seq s)
         (not (re-find meta-pattern s))
         (not (and (str/starts-with? s "{")
                   (str/ends-with? s "}"))))))

(defn narration-image-visible?
  [image-url]
  (let [s (some-> image-url str/trim)]
    (seq s)))

(defn visible-entry?
  [entry]
  (and (visible-source? (:narration/source entry))
       (or (narration-text-visible? (:narration/text entry))
           (narration-image-visible? (:narration/image-url entry)))))
