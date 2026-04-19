(ns ogres.app.ai.text
  (:require [clojure.string :as str]))

(def ^:private structured-line-patterns
  [#"^\s*[\{\}\[\],]+\s*$"
   #"^\s*\"[^\"]+\"\s*:\s*.*$"
   #"^\s*[\w\-]+\s*:\s*[\{\[].*$"
   #"^\s*(?:\d+\s*:\s*)?[\{\[].*[\}\]]\s*,?\s*$"])

(defn- json-string?
  [text]
  (try
    (js/JSON.parse text)
    true
    (catch :default _ false)))

(defn- structured-line?
  [line]
  (let [line (or line "")]
    (some #(re-find % line) structured-line-patterns)))

(defn narrative-only
  "Returns prose-only narration text, removing structured data output.
   Returns nil if no usable narrative remains."
  [text]
  (let [raw (some-> text str str/trim)]
    (when (seq raw)
      (if (json-string? raw)
        nil
        (let [without-code (-> raw
                               ;; Strip likely structured code fences.
                               (str/replace #"(?is)```(?:json|yaml|yml)\s*.*?```" "")
                               ;; Strip empty/backtick-only fences.
                               (str/replace #"(?is)```+\s*```+" "")
                               (str/replace #"```" ""))
              lines        (->> (str/split-lines without-code)
                                (remove structured-line?)
                                (map str/trim)
                                (remove str/blank?))
              cleaned      (some-> (str/join "\n" lines) str/trim)]
          (when (seq cleaned)
            cleaned))))))

