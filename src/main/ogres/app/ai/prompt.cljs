(ns ogres.app.ai.prompt
  (:require [datascript.core :as ds]
            [ogres.app.const :refer [grid-size]]))

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

(defn- format-token [t terrain-map]
  (let [pt      (:object/point t)
        terrain (when terrain-map (get terrain-map (:db/id t)))]
    (str "  - id: " (:db/id t)
         ", label: \"" (or (:token/label t) "Unknown") "\""
         (when pt (str ", pos: (" (.-x pt) ", " (.-y pt) ")"))
         (when (:token/size t) (str ", size: " (:token/size t) "ft"))
         (when (number? (:token/light t)) (str ", light: " (:token/light t) "ft"))
         (when (seq (:token/flags t))
           (str ", flags: [" (apply str (interpose ", " (map name (:token/flags t)))) "]"))
         (when terrain (str ", terrain: \"" terrain "\""))
         "\n")))

(defn- player-token? [t]
  (contains? (set (:token/flags t)) :player))

(defn- format-token-visibility [t visibility-map]
  (let [ctx     (when visibility-map (get visibility-map (:db/id t)))
        radius  (or (:radius-squares ctx) 10)
        cover   (or (:cover ctx) "unknown")
        foliage (or (:foliage ctx) "unknown")
        summary (or (:summary ctx) "Local details not detected.")]
    (str "  - id: " (:db/id t)
         ", label: \"" (or (:token/label t) "Unknown") "\""
         ", visible-radius: ~" radius " squares"
         ", cover: \"" cover "\""
         ", foliage: \"" foliage "\""
         ", summary: \"" summary "\"\n")))

(defn serialize-game-state
  "Serializes the current scene's game state from the DataScript database
   into a text block suitable for an LLM system prompt.
   Optional terrain-map is token-id -> terrain string.
   Optional visibility-map is token-id -> local visibility context."
  ([db] (serialize-game-state db nil nil))
  ([db terrain-map] (serialize-game-state db terrain-map nil))
  ([db terrain-map visibility-map]
  (let [user  (ds/entity db [:db/ident :user])
        scene (-> user :user/camera :camera/scene)
        sid   (:db/id scene)
        gs    (or (:scene/grid-size scene) grid-size)]
    (when sid
      (let [all-tokens (ds/pull-many db token-pull (map :db/id (:scene/tokens scene)))
            players    (filter player-token? all-tokens)
            npcs       (remove player-token? all-tokens)
            initiative (ds/pull-many db token-pull (map :db/id (:scene/initiative scene)))
            rounds     (:initiative/rounds scene)]
        (str
         "SCENE: " (or (:scene/label scene) "Unnamed") "\n"
         "GRID SIZE: " gs "px per tile (each tile = 5 feet)\n"
         "\nPLAYER TOKENS (do NOT move or remove these):\n"
         (if (seq players)
           (apply str (map #(format-token % terrain-map) players))
           "  (none)\n")
         "\nPLAYER LOCAL VISIBILITY (~10 squares by default, adjusted by stats):\n"
         (if (seq players)
           (apply str (map #(format-token-visibility % visibility-map) players))
           "  (none)\n")
         "\nNPC LOCAL VISIBILITY (~10 squares by default, adjusted by stats):\n"
         (if (seq npcs)
           (apply str (map #(format-token-visibility % visibility-map) npcs))
           "  (none)\n")
         "\nNPC/MONSTER TOKENS (you control these):\n"
         (if (seq npcs)
           (apply str (map #(format-token % terrain-map) npcs))
           "  (none)\n")
         (when (seq initiative)
           (str
            "\nINITIATIVE TRACKER:\n"
            (apply str
              (for [t (sort-by (comp - (fnil identity 0) :initiative/roll) initiative)]
                (str "  - id: " (:db/id t)
                     ", label: \"" (or (:token/label t) "Unknown") "\""
                     ", roll: " (or (:initiative/roll t) "?")
                     (when (:initiative/health t)
                       (str ", hp: " (:initiative/health t)))
                     (when (seq (:token/flags t))
                       (str ", flags: [" (apply str (interpose ", " (map name (:token/flags t)))) "]"))
                     "\n")))
            "ROUND: " (or rounds 0) "\n"))))))))

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
   "- DM responses and narrate text must be plain natural language only: descriptions, dialogue, and atmosphere.\n"
   "- Never output JSON, YAML, XML, code blocks, tables, key-value lists, or any other structured data format in narration.\n"
   "- For sensory narration, describe only what is visible in each player's local visibility radius (about 10 squares unless stats change it).\n"
   "- Apply the same local-visibility constraint to NPC observations; avoid map-wide omniscient descriptions.\n"
   "- Include nearby cover and foliage details from the LOCAL VISIBILITY sections whenever relevant.\n"
   "- Do NOT use move_token on player-flagged tokens — use move_player_token instead.\n"
   "- Use move_player_token ONLY when a player explicitly states their character moves (e.g. 'I move north', 'I go east 2 squares', 'I run to the door'). Infer direction from their message.\n"
   "- Do not move player tokens unless the player asked for it in this message.\n"
   "- Keep narration under 100 words per turn.\n"
   "- Position coordinates are in pixels. The grid cell size is " scene-grid-size "px (= 5 feet).\n"
   "- Snap token positions to grid centers: x = col * " scene-grid-size " + " (/ scene-grid-size 2)
   ", y = row * " scene-grid-size " + " (/ scene-grid-size 2) ".\n"
   "- Token IDs are integers. Use the exact IDs from the game state below.\n"
   "- If there is nothing to do, call narrate with brief flavor text and no other tools.\n"
   "\n"
   "CURRENT GAME STATE:\n"
   (or game-state "(empty scene)")))
