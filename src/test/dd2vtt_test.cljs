(ns dd2vtt-test
  (:require [cljs.test :refer-macros [deftest is testing]]
            [ogres.app.const :refer [grid-size]]
            [ogres.app.dd2vtt :as dd2vtt]))

(def ^:private minimal-uvtt
  "{\"format\":0.3,
    \"resolution\":{\"map_size\":{\"x\":10,\"y\":8},\"pixels_per_grid\":70},
    \"line_of_sight\":[[{\"x\":0,\"y\":0},{\"x\":0,\"y\":5}],
                      [{\"x\":3,\"y\":1},{\"x\":5,\"y\":1},{\"x\":5,\"y\":3}]],
    \"portals\":[{\"bounds\":[{\"x\":2,\"y\":0},{\"x\":3,\"y\":0}],\"closed\":true},
                 {\"bounds\":[{\"x\":7,\"y\":4},{\"x\":8,\"y\":4}],\"closed\":false}],
    \"image\":\"\"}")

(deftest parse-text
  (let [parsed (dd2vtt/parse-text minimal-uvtt "test.png")]
    (testing "map dimensions"
      (is (= 10 (:map-cells-x parsed)))
      (is (= 8 (:map-cells-y parsed))))
    (testing "walls are scaled from grid units to pixel space"
      (let [walls (:walls parsed)]
        ;; First polyline: 1 segment (0,0)->(0,5)
        ;; Second polyline: 2 segments (3,1)->(5,1), (5,1)->(5,3)
        (is (= 3 (count walls)))
        (is (= [0 0 0 (* 5 grid-size)] (first walls)))))
    (testing "doors preserve closed state and scale coordinates"
      (let [doors (:doors parsed)]
        (is (= 2 (count doors)))
        (is (true?  (:closed (first doors))))
        (is (false? (:closed (second doors))))
        (is (= [(* 2 grid-size) 0 (* 3 grid-size) 0]
               (first (:segments (first doors)))))))
    (testing "grid-size set to internal grid size"
      (is (= grid-size (:grid-size parsed))))))
