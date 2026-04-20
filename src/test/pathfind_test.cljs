(ns pathfind-test
  (:require [cljs.test :refer-macros [deftest is testing]]
            [ogres.app.const :refer [grid-size half-size]]
            [ogres.app.pathfind :as pathfind]))

(defn- cell [col row]
  [col row])

(deftest cell-conversions
  (testing "pixel -> cell at cell origin"
    (is (= [0 0] (pathfind/px->cell 0 0)))
    (is (= [1 1] (pathfind/px->cell grid-size grid-size)))
    (is (= [2 3] (pathfind/px->cell (* 2 grid-size) (* 3 grid-size)))))
  (testing "cell -> pixel returns the cell center"
    (is (= [half-size half-size] (pathfind/cell->px [0 0])))
    (is (= [(+ grid-size half-size) (+ grid-size half-size)]
           (pathfind/cell->px [1 1])))))

(deftest no-walls-direct-path
  (testing "path in an empty room is short and reaches the goal"
    (let [p (pathfind/find-path
             [] []
             half-size half-size                    ;; (0,0)
             (+ (* 3 grid-size) half-size) half-size ;; (3,0)
             )]
      (is (some? p))
      (is (= (cell 0 0) (first p)))
      (is (= (cell 3 0) (last p))))))

(deftest start-equals-goal
  (let [p (pathfind/find-path [] [] half-size half-size half-size half-size)]
    (is (= [(cell 0 0)] p))))

(deftest routes-around-a-wall
  (testing "A vertical wall between (0,0) and (2,0) forces the path to detour"
    ;; Wall stretching from y=-grid-size*3 to y=grid-size*3 at x=grid-size
    ;; This separates cell (0,*) from cell (1,*) horizontally at row 0.
    ;; But rows above and below (outside wall extent) remain passable.
    (let [wall-x (* 1.5 grid-size)   ;; wall between col 1 and col 2
          walls [[wall-x (* -1 half-size) wall-x (* 2.5 grid-size)]]
          p (pathfind/find-path
             walls []
             half-size half-size                   ;; (0,0)
             (+ (* 3 grid-size) half-size) half-size ;; (3,0)
             )]
      (is (some? p))
      (is (= (cell 0 0) (first p)))
      (is (= (cell 3 0) (last p)))
      (is (> (count p) 4) "Detour path should be longer than direct"))))

(deftest no-path-when-fully-enclosed
  (testing "A ring of walls around the start traps it"
    ;; Walls forming a box around cell (0,0).
    (let [walls [[0 0 grid-size 0]
                 [grid-size 0 grid-size grid-size]
                 [0 grid-size grid-size grid-size]
                 [0 0 0 grid-size]]
          p (pathfind/find-path
             walls []
             half-size half-size                     ;; inside the box
             (+ (* 5 grid-size) half-size) half-size ;; outside the box
             )]
      (is (nil? p)))))

(deftest closed-door-blocks-open-does-not
  (let [door-x (* 1.5 grid-size)
        doors-closed [{:closed true
                       :segments [[door-x (* -1 half-size)
                                   door-x (* 2.5 grid-size)]]}]
        doors-open   [{:closed false
                       :segments [[door-x (* -1 half-size)
                                   door-x (* 2.5 grid-size)]]}]
        sx half-size sy half-size
        gx (+ (* 3 grid-size) half-size) gy half-size]
    (is (some? (pathfind/find-path [] doors-open  sx sy gx gy)))
    (let [p (pathfind/find-path [] doors-closed sx sy gx gy)]
      (is (or (nil? p) (> (count p) 4))
          "Closed door forces a detour (or no path)"))))
