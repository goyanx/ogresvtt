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

(defn serialize-game-state
  "Serializes the current scene's game state from the DataScript database
   into a text block suitable for an LLM system prompt."
  [db]
  (let [user  (ds/entity db [:db/ident :user])
        scene (-> user :user/camera :camera/scene)
        sid   (:db/id scene)
        gs    (or (:scene/grid-size scene) grid-size)]
    (when sid
      (let [tokens     (ds/pull-many db token-pull (map :db/id (:scene/tokens scene)))
            initiative (ds/pull-many db token-pull (map :db/id (:scene/initiative scene)))
            rounds     (:initiative/rounds scene)]
        (str
         "SCENE: " (or (:scene/label scene) "Unnamed") "\n"
         "GRID SIZE: " gs "px per tile (each tile = 5 feet)\n"
         "\nTOKENS ON BOARD:\n"
         (if (seq tokens)
           (apply str
             (for [t tokens
                   :let [pt (:object/point t)]]
               (str "  - id: " (:db/id t)
                    ", label: \"" (or (:token/label t) "Unknown") "\""
                    (when pt (str ", pos: (" (.-x pt) ", " (.-y pt) ")"))
                    (when (:token/size t) (str ", size: " (:token/size t) "ft"))
                    (when (seq (:token/flags t))
                      (str ", flags: [" (apply str (interpose ", " (map name (:token/flags t)))) "]"))
                    "\n")))
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
   "- Do NOT move or remove tokens with the 'player' flag — they are controlled by players.\n"
   "- Keep narration under 100 words per turn.\n"
   "- Position coordinates are in pixels. The grid cell size is " scene-grid-size "px (= 5 feet).\n"
   "- Snap token positions to grid centers: x = col * " scene-grid-size " + " (/ scene-grid-size 2)
   ", y = row * " scene-grid-size " + " (/ scene-grid-size 2) ".\n"
   "- Token IDs are integers. Use the exact IDs from the game state below.\n"
   "- If there is nothing to do, call narrate with brief flavor text and no other tools.\n"
   "\n"
   "CURRENT GAME STATE:\n"
   (or game-state "(empty scene)")))
