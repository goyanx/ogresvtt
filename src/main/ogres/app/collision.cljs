(ns ogres.app.collision
  "Pure 2D geometry helpers for checking whether paths or points are
   obstructed by wall segments. All coordinates are expected to be in
   the internal scene pixel space (same as token positions).

   A wall segment is `[x1 y1 x2 y2]`. A door is
   `{:closed bool :segments [[x1 y1 x2 y2] ...]}`; closed doors block
   movement just like walls, open doors do not.")

(defn ^:private cross
  "Signed cross product of vectors (o->a) and (o->b)."
  [ox oy ax ay bx by]
  (- (* (- ax ox) (- by oy))
     (* (- ay oy) (- bx ox))))

(defn ^:private on-segment?
  "Given three collinear points, checks whether q lies on segment pr."
  [px py qx qy rx ry]
  (and (<= (min px rx) qx (max px rx))
       (<= (min py ry) qy (max py ry))))

(defn segments-intersect?
  "Returns true if segments AB and CD share at least one point."
  [ax ay bx by cx cy dx dy]
  (let [d1 (cross cx cy dx dy ax ay)
        d2 (cross cx cy dx dy bx by)
        d3 (cross ax ay bx by cx cy)
        d4 (cross ax ay bx by dx dy)]
    (or (and (or (and (pos? d1) (neg? d2)) (and (neg? d1) (pos? d2)))
             (or (and (pos? d3) (neg? d4)) (and (neg? d3) (pos? d4))))
        (and (zero? d1) (on-segment? cx cy ax ay dx dy))
        (and (zero? d2) (on-segment? cx cy bx by dx dy))
        (and (zero? d3) (on-segment? ax ay cx cy bx by))
        (and (zero? d4) (on-segment? ax ay dx dy bx by)))))

(defn ^:private door-blockers
  "Returns the flat list of blocking segments contributed by doors,
   i.e. only the segments of closed doors."
  [doors]
  (into []
        (comp (filter :closed) (mapcat :segments))
        doors))

(defn path-blocked?
  "Returns true if the straight line from (x1,y1) to (x2,y2) crosses any
   wall segment or any closed door segment."
  ([walls x1 y1 x2 y2]
   (path-blocked? walls nil x1 y1 x2 y2))
  ([walls doors x1 y1 x2 y2]
   (let [blockers (into (vec walls) (door-blockers (or doors [])))]
     (boolean
      (some (fn [[ax ay bx by]]
              (segments-intersect? x1 y1 x2 y2 ax ay bx by))
            blockers)))))

(defn ^:private dist-point-to-segment
  "Shortest distance from point (px,py) to segment AB."
  [px py ax ay bx by]
  (let [dx (- bx ax)
        dy (- by ay)
        len2 (+ (* dx dx) (* dy dy))]
    (if (zero? len2)
      (js/Math.hypot (- px ax) (- py ay))
      (let [t (max 0 (min 1 (/ (+ (* (- px ax) dx) (* (- py ay) dy)) len2)))
            cx (+ ax (* t dx))
            cy (+ ay (* t dy))]
        (js/Math.hypot (- px cx) (- py cy))))))

(defn point-near-wall?
  "Returns true if (px,py) lies within `radius` pixels of any wall."
  [walls px py radius]
  (boolean
   (some (fn [[ax ay bx by]]
           (<= (dist-point-to-segment px py ax ay bx by) radius))
         walls)))

(defn nearest-wall-distance
  "Returns the distance in pixels from (px,py) to the closest wall,
   or js/Infinity if the scene has no walls."
  [walls px py]
  (reduce
   (fn [acc [ax ay bx by]]
     (min acc (dist-point-to-segment px py ax ay bx by)))
   js/Infinity
   walls))
