(ns ogres.app.ai.prompt
  (:require [datascript.core :as ds]
            [clojure.string :as str]
            [ogres.app.collision :as collision]
            [ogres.app.const :refer [grid-size]]))

(def ^:private near-wall-distance
  "Pixel radius within which a token is flagged as 'near a wall'.
   One grid cell is the natural threshold."
  grid-size)

(def ^:private token-pull
  [:db/id
   :token/label
   :token/flags
   :token/size
   :token/light
   :object/point
   :initiative/roll
   :initiative/health
   :initiative/suffix])

(defn- initiative-order
  "Sort order used by the Initiative panel and turn advancement:
   roll descending, then id descending."
  [a b]
  (let [f (juxt :initiative/roll :db/id)]
    (compare (f b) (f a))))

(defn- format-token
  ([t] (format-token t nil grid-size))
  ([t walls scene-grid-size]
   (let [pt (:object/point t)
         wall-distance (or scene-grid-size near-wall-distance)
         near-wall? (and pt (seq walls)
                         (collision/point-near-wall?
                          walls (.-x pt) (.-y pt) wall-distance))]
     (str "  - id: " (:db/id t)
          ", label: \"" (or (:token/label t) "Unknown") "\""
          (when pt (str ", pos: (" (.-x pt) ", " (.-y pt) ")"))
          (when (:token/size t) (str ", size: " (:token/size t) "ft"))
          (when (seq (:token/flags t))
            (str ", flags: [" (apply str (interpose ", " (map name (:token/flags t)))) "]"))
          (when near-wall? ", near_wall: true")
          "\n"))))

(defn- player-token? [t]
  (contains? (set (:token/flags t)) :player))

(def ^:private max-proximity-rows
  "Maximum number of NPC proximity rows included in the prompt."
  24)

(defn- px->ft
  [px scene-grid-size]
  (let [ft (* (/ px scene-grid-size) 5)
        rd (js/Math.round ft)]
    (if (< (js/Math.abs (- ft rd)) 0.001) rd
        (.toFixed ft 1))))

(defn- distance-px
  [a b]
  (js/Math.hypot (- (.-x b) (.-x a))
                 (- (.-y b) (.-y a))))

(defn- npc-proximity-lines
  [npcs players walls doors scene-grid-size]
  (let [pairs
        (for [npc npcs
              :let [npc-point (:object/point npc)]
              :when npc-point
              player players
              :let [player-point (:object/point player)]
              :when player-point
              :let [px-distance (distance-px npc-point player-point)]]
          {:npc npc
           :player player
           :px-distance px-distance
           :feet-distance (* (/ px-distance scene-grid-size) 5)
           :blocked? (collision/path-blocked?
                      walls doors
                      (.-x npc-point) (.-y npc-point)
                      (.-x player-point) (.-y player-point))})
        nearest-by-npc
        (->> pairs
             (group-by (comp :db/id :npc))
             vals
             (map (fn [rows] (first (sort-by :feet-distance rows))))
             (sort-by :feet-distance)
             (take max-proximity-rows))]
    (when (seq nearest-by-npc)
      (str
       "\nNPC PROXIMITY TO PLAYERS (authoritative distance cues; center-to-center):\n"
       (apply str
              (for [{:keys [npc player px-distance feet-distance blocked?]} nearest-by-npc]
                (str "  - NPC \"" (or (:token/label npc) "Unknown") "\" (id " (:db/id npc) ")"
                     " -> nearest player \"" (or (:token/label player) "Unknown") "\" (id " (:db/id player) "): "
                     (px->ft px-distance scene-grid-size) "ft"
                     ", adjacent_5ft: " (if (<= feet-distance 5) "true" "false")
                     ", line_of_sight_blocked: " (if blocked? "true" "false")
                     "\n")))))))

(def ^:private max-blocked-pairs
  "Maximum number of blocked-LOS pairs to include in the prompt. Caps
   the worst case for busy maps so the prompt stays compact."
  20)

(defn- blocked-pairs
  "Returns a sequence of [a b] pairs of tokens whose line-of-sight is
   blocked by a wall or closed door. Capped at `max-blocked-pairs`."
  [tokens walls doors]
  (let [with-pts (filter :object/point tokens)
        pairs    (for [[a & rest-ts] (iterate rest with-pts)
                       :while a
                       b rest-ts] [a b])]
    (into []
          (comp (filter (fn [[a b]]
                          (let [pa (:object/point a)
                                pb (:object/point b)]
                            (collision/path-blocked?
                             walls doors
                             (.-x pa) (.-y pa) (.-x pb) (.-y pb)))))
                (take max-blocked-pairs))
          pairs)))

(defn- format-blocked-pair [[a b]]
  (str "  - "
       (or (:token/label a) (str "#" (:db/id a)))
       " (id " (:db/id a) ") <-> "
       (or (:token/label b) (str "#" (:db/id b)))
       " (id " (:db/id b) ")\n"))

(defn- point-in-trigger-rect?
  [point shape]
  (let [origin (:object/point shape)
        [delta] (:shape/points shape)
        x (.-x point)
        y (.-y point)
        x1 (.-x origin)
        y1 (.-y origin)
        x2 (+ x1 (.-x delta))
        y2 (+ y1 (.-y delta))]
    (and (<= (min x1 x2) x (max x1 x2))
         (<= (min y1 y2) y (max y1 y2)))))

(defn- area-context
  [shape]
  (let [raw (:trigger-area/context shape)
        txt (some-> raw str str/trim not-empty)]
    (when txt txt)))

(defn- format-token-region-context
  [token shape]
  (let [token-label (or (:token/label token) "Unknown")
        region-label (or (:trigger-area/label shape)
                         (:trigger-area/region-key shape)
                         "Unnamed region")
        context (area-context shape)
        indented (when context (str/replace context #"\r?\n" "\n      "))]
    (str "  - token \"" token-label "\" (id " (:db/id token) ") in region \"" region-label "\"\n"
         (when (seq indented)
           (str "      " indented "\n")))))

(defn- token-region-context-lines
  [scene tokens]
  (let [regions (->> (:scene/shapes scene)
                     (filter
                       (fn [shape]
                         (and (= :shape/rect (:object/type shape))
                              (:trigger-area/region-key shape)
                              (:trigger-area/enabled? shape true)))))
        matches
        (for [token tokens
              :let [point (:object/point token)]
              :when point
              region regions
              :when (and (seq (area-context region))
                         (point-in-trigger-rect? point region))]
          (format-token-region-context token region))]
    (if (seq matches)
      (str "\nAREA REGION CONTEXT (use this when narrating actions inside these zones):\n"
           (apply str matches))
      "")))

(defn serialize-game-state
  "Serializes the current scene's game state from the DataScript database
   into a text block suitable for an LLM system prompt."
  [db]
  (let [user  (ds/entity db [:db/ident :user])
        scene (-> user :user/camera :camera/scene)
        sid   (:db/id scene)
        gs    (or (:scene/grid-size scene) grid-size)
        walls (or (:scene/walls scene) [])
        doors (or (:scene/doors scene) [])
        closed-doors (count (filter :closed doors))]
    (when sid
      (let [all-tokens (ds/pull-many db token-pull (map :db/id (:scene/tokens scene)))
            players    (filter player-token? all-tokens)
            npcs       (remove player-token? all-tokens)
            initiative (ds/pull-many db token-pull (map :db/id (:scene/initiative scene)))
            rounds     (:initiative/rounds scene)
            turn-id    (:db/id (:initiative/turn scene))
            played-ids (into #{} (map :db/id) (:initiative/played scene))
            region-context (token-region-context-lines scene all-tokens)
            proximity-lines (npc-proximity-lines npcs players walls doors gs)
            blocked    (when (seq walls) (blocked-pairs all-tokens walls doors))]
        (str
         "SCENE: " (or (:scene/label scene) "Unnamed") "\n"
         "GRID SIZE: " gs "px per tile (each tile = 5 feet)\n"
         (when (or (seq walls) (seq doors))
           (str "MAP GEOMETRY: " (count walls) " wall segments, "
                (count doors) " doors (" closed-doors " closed)\n"
                "  Tokens cannot move through walls or closed doors.\n"))
         "\nPLAYER TOKENS (do NOT move or remove these):\n"
         (if (seq players)
           (apply str (map #(format-token % walls gs) players))
           "  (none)\n")
         "\nNPC/MONSTER TOKENS (you control these):\n"
         (if (seq npcs)
           (apply str (map #(format-token % walls gs) npcs))
           "  (none)\n")
         proximity-lines
         (when (seq blocked)
           (str "\nBLOCKED LINE OF SIGHT (these pairs cannot see each other):\n"
                (apply str (map format-blocked-pair blocked))))
         region-context
         (when (seq initiative)
           (str
            "\nINITIATIVE TRACKER:\n"
            "CURRENT TURN ID: " (or turn-id "none") "\n"
            (apply str
              (for [t (sort initiative-order initiative)
                    :let [id (:db/id t)]]
                (str "  - id: " (:db/id t)
                     ", label: \"" (or (:token/label t) "Unknown") "\""
                     ", roll: " (or (:initiative/roll t) "?")
                     (when (:initiative/health t)
                       (str ", hp: " (:initiative/health t)))
                     (when (seq (:token/flags t))
                       (str ", flags: [" (apply str (interpose ", " (map name (:token/flags t)))) "]"))
                     (when (= id turn-id)
                       ", current_turn: true")
                     (when (contains? played-ids id)
                       ", played: true")
                     "\n")))
            "ROUND: " (or rounds 0) "\n")))))))

(defn build-system-prompt
  "Builds the full system prompt for the AI DM, combining the scenario
   context with rules and the current game state."
  [scenario game-state scene-grid-size]
  (str
   "You are an AI Dungeon Master running a tabletop RPG encounter.\n"
   "Your job is to narrate events and control NPC/monster tokens on the board.\n"
   "\n"
   (when (seq scenario)
     (str "SCENARIO:\n" scenario "\n\n"))
   "RULES:\n"
   "- Use the provided tool functions to take actions.\n"
   "- Always call the 'narrate' tool once per turn to describe what happens.\n"
   "- If initiative is active, only take actions for the token marked current_turn: true in INITIATIVE TRACKER.\n"
   "- Do NOT use move_token on player-flagged tokens — use move_player_token instead.\n"
   "- Use move_player_token ONLY when a player explicitly states their character moves (e.g. 'I move north', 'I go east 2 squares', 'I run to the door'). Infer direction from their message.\n"
   "- Do not move player tokens unless the player asked for it in this message.\n"
   "- When any PC/NPC roll happens this turn, include the actual rolled number(s) in narration.\n"
   "- Keep narration under 100 words per turn.\n"
   "- Always respond in English only (narration, tool text, and reasoning). Never output Thai or any other language.\n"
   "- Position coordinates are in pixels. The grid cell size is " scene-grid-size "px (= 5 feet).\n"
   "- For proximity decisions, use the provided feet distances. A token is adjacent/melee only at 5ft or less.\n"
   "- Snap token positions to grid centers: x = col * " scene-grid-size " + " (/ scene-grid-size 2)
   ", y = row * " scene-grid-size " + " (/ scene-grid-size 2) ".\n"
   "- Token IDs are integers. Use the exact IDs from the game state below.\n"
   "- If the map has walls or closed doors, movement attempts that cross them will be rejected. Pick a path that goes around obstacles.\n"
   "- Use BLOCKED LINE OF SIGHT data: a token cannot see or shoot through a wall. An NPC should not act on information its line of sight does not give it.\n"
   "- If there is nothing to do, call narrate with brief flavor text and no other tools.\n"
   "\n"
   "CURRENT GAME STATE:\n"
   (or game-state "(empty scene)")))

