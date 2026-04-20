(ns collision-test
  (:require [cljs.test :refer-macros [deftest is testing]]
            [ogres.app.collision :as collision]))

(deftest segments-intersect
  (testing "crossing segments"
    (is (collision/segments-intersect? 0 0 10 10  0 10 10 0)))
  (testing "parallel segments"
    (is (not (collision/segments-intersect? 0 0 10 0  0 5 10 5))))
  (testing "disjoint segments"
    (is (not (collision/segments-intersect? 0 0 1 1  10 10 11 11))))
  (testing "T-junction (endpoint on segment)"
    (is (collision/segments-intersect? 0 0 10 0  5 0 5 5)))
  (testing "shared endpoint"
    (is (collision/segments-intersect? 0 0 10 0  10 0 10 10))))

(deftest path-blocked
  (let [walls [[5 0 5 10]]]
    (testing "path crossing a wall is blocked"
      (is (collision/path-blocked? walls 0 5 10 5)))
    (testing "path parallel to a wall is not blocked"
      (is (not (collision/path-blocked? walls 0 5 4 5))))
    (testing "closed door blocks movement"
      (is (collision/path-blocked?
           [] [{:closed true :segments [[5 0 5 10]]}]
           0 5 10 5)))
    (testing "open door does not block movement"
      (is (not (collision/path-blocked?
                [] [{:closed false :segments [[5 0 5 10]]}]
                0 5 10 5))))))

(deftest point-near-wall
  (let [walls [[0 0 10 0]]]
    (is (collision/point-near-wall? walls 5 2 5))
    (is (not (collision/point-near-wall? walls 5 20 5)))))
