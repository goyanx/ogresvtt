(ns tool-dispatch-test
  (:require [cljs.test :refer-macros [deftest is testing]]
            [datascript.core :as ds]
            [ogres.app.ai.tool-dispatch :as td]
            [ogres.app.const :refer [grid-size]]
            [ogres.app.provider.state :refer [initial-data]]
            [ogres.app.vec :as vec :refer [Vec2]]))

(defn- build-scene
  "Builds a DataScript db with a single scene, a single NPC token at
   the given position, and optional walls and doors. Returns
   [db token-id]."
  [& {:keys [token-pos walls doors scene-grid-size]
      :or {token-pos (Vec2. 35 35) walls [] doors [] scene-grid-size grid-size}}]
  (let [db0   (initial-data true)
        user  (ds/entity db0 [:db/ident :user])
        sid   (:db/id (:camera/scene (:user/camera user)))
        tx    [{:db/id sid
                :scene/grid-size scene-grid-size
                :scene/walls walls
                :scene/doors doors
                :scene/tokens
                [{:db/id -10
                  :object/type :token/token
                  :object/point token-pos
                  :token/label "Goblin"}]}]
        report (ds/with db0 tx)
        db     (:db-after report)
        token-id (get (:tempids report) -10)]
    [db token-id]))

(defn- captured-dispatcher []
  (let [captured (atom [])]
    [captured
     (fn [& args] (swap! captured conj args))]))

(deftest move-token-respects-walls
  (testing "move_token succeeds when path is clear"
    (let [[db tid] (build-scene :token-pos (Vec2. 35 35))
          [log dispatch] (captured-dispatcher)
          r  (td/dispatch-tool dispatch db "move_token"
                               {:token_id tid :x 175 :y 35} {})]
      (is (:ok r))
      (is (= 1 (count @log)))))
  (testing "move_token fails when a wall blocks the path"
    (let [walls [[100 0 100 200]]
          [db tid] (build-scene :token-pos (Vec2. 35 35) :walls walls)
          [log dispatch] (captured-dispatcher)
          r  (td/dispatch-tool dispatch db "move_token"
                               {:token_id tid :x 175 :y 35} {})]
      (is (not (:ok r)))
      (is (zero? (count @log))
          "No dispatch is called when the path is blocked.")))
  (testing "closed door blocks movement; open door does not"
    (let [[db-c tid-c] (build-scene :token-pos (Vec2. 35 35)
                                    :doors [{:closed true  :segments [[100 0 100 200]]}])
          [db-o tid-o] (build-scene :token-pos (Vec2. 35 35)
                                    :doors [{:closed false :segments [[100 0 100 200]]}])
          [_ d1] (captured-dispatcher)
          [_ d2] (captured-dispatcher)]
      (is (not (:ok (td/dispatch-tool d1 db-c "move_token"
                                       {:token_id tid-c :x 175 :y 35} {}))))
      (is (:ok (td/dispatch-tool d2 db-o "move_token"
                                  {:token_id tid-o :x 175 :y 35} {}))))))

(deftest move-player-token-respects-walls
  (testing "move_player_token fails when path crosses a wall"
    (let [walls [[100 0 100 200]]
          [db tid] (build-scene :token-pos (Vec2. 35 35) :walls walls)
          [log dispatch] (captured-dispatcher)
          r  (td/dispatch-tool dispatch db "move_player_token"
                               {:token_id tid :direction "east" :squares 3} {})]
      (is (not (:ok r)))
      (is (zero? (count @log))))))

(deftest movement-uses-scene-grid-size
  (testing "move_player_token moves by active scene grid size"
    (let [[db tid] (build-scene :token-pos (Vec2. 50 50) :scene-grid-size 100)
          [log dispatch] (captured-dispatcher)
          r (td/dispatch-tool dispatch db "move_player_token"
                              {:token_id tid :direction "east" :squares 1} {})]
      (is (:ok r))
      (is (= 1 (count @log)))
      (let [[event-name moved-id delta] (first @log)]
        (is (= :objects/translate event-name))
        (is (= tid moved-id))
        (is (= (Vec2. 100 0) delta)))))
  (testing "move_token snap-to-grid uses active scene grid size"
    (let [[db tid] (build-scene :token-pos (Vec2. 50 50) :scene-grid-size 100)
          [log dispatch] (captured-dispatcher)
          r (td/dispatch-tool dispatch db "move_token"
                              {:token_id tid :x 151 :y 49} {})]
      (is (:ok r))
      (is (= 1 (count @log)))
      (let [[event-name moved-id delta] (first @log)]
        (is (= :objects/translate event-name))
        (is (= tid moved-id))
        ;; 151,49 snaps to 150,50 on a 100px grid (centers at 50,150,...)
        (is (= (Vec2. 100 0) delta))))))

(deftest plan-path-tool
  (testing "returns waypoints when a path exists"
    (let [[db _] (build-scene)
          r  (td/dispatch-tool (fn [& _]) db "plan_path"
                               {:from_x 35 :from_y 35
                                :to_x 245 :to_y 35} {})]
      (is (:ok r))
      (is (vector? (:waypoints r)))
      (is (>= (count (:waypoints r)) 2))))
  (testing "returns an error when the goal is unreachable"
    ;; Box the start in with walls.
    (let [walls [[0 0 70 0] [70 0 70 70] [0 70 70 70] [0 0 0 70]]
          [db _] (build-scene :walls walls)
          r  (td/dispatch-tool (fn [& _]) db "plan_path"
                               {:from_x 35 :from_y 35
                                :to_x 500 :to_y 35} {})]
      (is (not (:ok r))))))

(deftest set-door-state-tool
  (testing "valid index dispatches the state change event"
    (let [[db _] (build-scene
                  :doors [{:closed true :segments [[0 0 10 10]]}])
          [log dispatch] (captured-dispatcher)
          r  (td/dispatch-tool dispatch db "set_door_state"
                               {:door_index 0 :closed false} {})]
      (is (:ok r))
      (is (= 1 (count @log)))
      (let [[topic idx closed?] (first @log)]
        (is (= :scene/set-door-state topic))
        (is (= 0 idx))
        (is (false? closed?)))))
  (testing "out-of-range index fails without dispatching"
    (let [[db _] (build-scene :doors [])
          [log dispatch] (captured-dispatcher)
          r  (td/dispatch-tool dispatch db "set_door_state"
                               {:door_index 5 :closed true} {})]
      (is (not (:ok r)))
      (is (zero? (count @log))))))
