(ns ogres.app.ai.tools)

(def tool-definitions
  [;; Query tool — in LangGraph mode the sidecar answers this locally.
   ;; In direct Ollama/Grok mode the answer is already in the system prompt.
   {:type "function"
    :function
    {:name "list_tokens"
     :description "List tokens currently on the board with their id, label, type (player/npc), position, size, hp, and flags. Call this to confirm token IDs before acting."
     :parameters
     {:type "object"
      :properties
      {:filter {:type "string"
                :enum ["all" "player" "npc"]
                :description "Which tokens to return. Omit for all."}}
      :required []}}}
   {:type "function"
    :function
    {:name "narrate"
     :description "Emit narration text visible to all players. Call this once per turn."
     :parameters
     {:type "object"
      :properties
      {:text {:type "string" :description "The narration text, under 100 words."}}
      :required ["text"]}}}
   {:type "function"
    :function
    {:name "move_token"
     :description "Move an existing NPC/monster token to a new grid position."
     :parameters
     {:type "object"
      :properties
      {:token_id {:type "integer" :description "The entity ID of the token."}
       :x {:type "integer" :description "Target x position in pixels, snapped to grid."}
       :y {:type "integer" :description "Target y position in pixels, snapped to grid."}}
      :required ["token_id" "x" "y"]}}}
   {:type "function"
    :function
    {:name "spawn_token"
     :description "Place a new NPC or monster token on the scene."
     :parameters
     {:type "object"
      :properties
      {:label {:type "string" :description "Display name for the token."}
       :x {:type "integer" :description "X position in pixels."}
       :y {:type "integer" :description "Y position in pixels."}
       :size {:type "integer" :description "Token diameter in feet (5=tiny, 10=medium, 15=large, 20=huge)."}}
      :required ["label" "x" "y"]}}}
   {:type "function"
    :function
    {:name "remove_token"
     :description "Remove a defeated or unnecessary token from the scene."
     :parameters
     {:type "object"
      :properties
      {:token_id {:type "integer" :description "The entity ID of the token."}}
      :required ["token_id"]}}}
   {:type "function"
    :function
    {:name "update_hp"
     :description "Set a token's current hit points (token must be in the initiative tracker)."
     :parameters
     {:type "object"
      :properties
      {:token_id {:type "integer" :description "The entity ID of the token."}
       :hp {:type "integer" :description "New hit point value."}}
      :required ["token_id" "hp"]}}}
   {:type "function"
    :function
    {:name "roll_initiative"
     :description "Add one or more tokens to the initiative tracker and roll for them."
     :parameters
     {:type "object"
      :properties
      {:token_ids {:type "array"
                   :items {:type "integer"}
                   :description "List of token entity IDs."}}
      :required ["token_ids"]}}}
   {:type "function"
    :function
    {:name "move_player_token"
     :description "Move a player-controlled token by a number of squares in a compass direction. Use this ONLY when the player explicitly says their character moves (e.g. 'I move north', 'I walk to the door'). Never use this on your own initiative."
     :parameters
     {:type "object"
      :properties
      {:token_id  {:type "integer" :description "Entity ID of the player token."}
       :direction {:type "string"
                   :enum ["north" "south" "east" "west"
                          "northeast" "northwest" "southeast" "southwest"]
                   :description "Direction the player is moving."}
       :squares   {:type "integer" :description "Number of grid squares to move. Defaults to 1."}}
      :required ["token_id" "direction"]}}}
   {:type "function"
    :function
    {:name "advance_turn"
     :description "Advance the initiative tracker to the next combatant's turn."
     :parameters
     {:type "object" :properties {}}}}])
