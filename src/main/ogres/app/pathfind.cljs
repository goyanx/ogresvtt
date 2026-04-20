(ns ogres.app.pathfind
  "Grid pathfinding around wall segments and closed doors.

   The scene is treated as an infinite grid of cells whose centers are at
   (col * cell + cell/2, row * cell + cell/2). An edge between two
   neighboring cell centers is walkable iff the straight line between
   those centers does not cross any wall or closed door segment.

   Uses A* with octile heuristic (supports 8-way movement)."
  (:require [ogres.app.collision :as collision]
            [ogres.app.const :refer [grid-size half-size]]))

(def ^:private directions
  "The eight neighbor offsets. Diagonals cost ~1.414, orthogonals 1."
  [[ 1  0 1.0] [-1  0 1.0] [ 0  1 1.0] [ 0 -1 1.0]
   [ 1  1 1.4142] [ 1 -1 1.4142] [-1  1 1.4142] [-1 -1 1.4142]])

(defn px->cell
  "Converts a pixel coordinate to its containing [col row] cell."
  [x y]
  [(js/Math.floor (/ x grid-size))
   (js/Math.floor (/ y grid-size))])

(defn cell->px
  "Returns the pixel center of a [col row] cell."
  [[col row]]
  [(+ (* col grid-size) half-size)
   (+ (* row grid-size) half-size)])

(defn ^:private octile
  "Octile distance heuristic (admissible for 8-way movement)."
  [[ax ay] [bx by]]
  (let [dx (js/Math.abs (- ax bx))
        dy (js/Math.abs (- ay by))]
    (+ (min dx dy)
       (* 1.4142 (js/Math.abs (- dx dy))))))

(defn ^:private walkable-edge?
  "True if moving from cell `a` to cell `b` is not blocked by walls/doors."
  [walls doors a b]
  (let [[ax ay] (cell->px a)
        [bx by] (cell->px b)]
    (not (collision/path-blocked? walls doors ax ay bx by))))

(defn ^:private reconstruct
  "Walks the came-from map back from `goal` to reconstruct the path."
  [came-from goal]
  (loop [cur goal path (list goal)]
    (if-let [prev (get came-from cur)]
      (recur prev (conj path prev))
      (vec path))))

(def ^:private default-max-nodes
  "Upper bound on A* expansions before bailing out. Prevents runaway
   search on maps with disconnected regions or massive grids."
  4000)

(defn find-path
  "Finds a path of [col row] cells from `start` (pixel) to `goal` (pixel)
   avoiding walls and closed doors. Returns a vector of cells (including
   start and goal cells) or nil if no path is found within `max-nodes`.

   Arguments:
     walls — vector of [x1 y1 x2 y2] segments
     doors — vector of {:closed bool :segments [...]} maps
     sx sy — start pixel coordinates
     gx gy — goal pixel coordinates"
  ([walls doors sx sy gx gy]
   (find-path walls doors sx sy gx gy default-max-nodes))
  ([walls doors sx sy gx gy max-nodes]
   (let [start (px->cell sx sy)
         goal  (px->cell gx gy)]
     (if (= start goal)
       [start]
       (loop [open       (sorted-set-by
                          (fn [[s1 c1] [s2 c2]]
                            (if (= s1 s2) (compare c1 c2) (compare s1 s2)))
                          [(octile start goal) start])
              g-score    {start 0}
              came-from  {}
              expanded   0]
         (cond
           (empty? open) nil
           (> expanded max-nodes) nil
           :else
           (let [[_ current] (first open)
                 open' (disj open (first open))]
             (if (= current goal)
               (reconstruct came-from goal)
               (let [[cc cr] current
                     g-cur   (g-score current)
                     updates
                     (for [[dc dr cost] directions
                           :let [nb [(+ cc dc) (+ cr dr)]]
                           :when (walkable-edge? walls doors current nb)
                           :let [tentative (+ g-cur cost)]
                           :when (< tentative (get g-score nb js/Infinity))]
                       [nb tentative])]
                 (let [new-g (reduce (fn [m [nb g]] (assoc m nb g))
                                     g-score updates)
                       new-cf (reduce (fn [m [nb _]] (assoc m nb current))
                                      came-from updates)
                       new-open (reduce
                                 (fn [s [nb g]]
                                   (conj s [(+ g (octile nb goal)) nb]))
                                 open' updates)]
                   (recur new-open new-g new-cf (inc expanded))))))))))))

(defn path-waypoints
  "Convenience: returns the pixel centers of the cells along the path, or
   nil if no path exists."
  [walls doors sx sy gx gy]
  (when-let [cells (find-path walls doors sx sy gx gy)]
    (mapv cell->px cells)))
