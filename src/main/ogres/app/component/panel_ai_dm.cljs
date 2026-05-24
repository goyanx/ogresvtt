(ns ogres.app.component.panel-ai-dm
  (:require [ogres.app.ai.core :as ai]
            [ogres.app.component :refer [icon]]
            [ogres.app.hooks :as hooks]
            [uix.core :as uix :refer [defui $]]))

(def ^:private query
  [[:user/host :default true]])

(defui ^:private field-row [{:keys [label children]}]
  ($ :label.ai-dm-field
    ($ :span.ai-dm-field-label label)
    children))

(defn ^:private parse-int-safe [value fallback]
  (let [n (js/parseInt value)]
    (if (js/isNaN n) fallback n)))

(defn ^:private parse-float-safe [value fallback]
  (let [n (js/parseFloat value)]
    (if (js/isNaN n) fallback n)))

(def ^:private comfy-preset-12gb-fast
  {:comfy-steps 16
   :comfy-width 832
   :comfy-height 512
   :comfy-batch-size 1
   :comfy-cfg 3.2
   :comfy-sampler-name "euler"
   :comfy-scheduler "normal"})

(def ^:private comfy-preset-12gb-quality
  {:comfy-steps 24
   :comfy-width 1024
   :comfy-height 576
   :comfy-batch-size 1
   :comfy-cfg 3.8
   :comfy-sampler-name "euler"
   :comfy-scheduler "normal"})

(defui ^:memo panel []
  (let [result (hooks/use-query query)
        {:keys [user/host]} result
        ctx (uix/use-context ai/context)
        [api-key set-api-key] (uix/use-state #(.getItem js/localStorage "ai-dm-api-key"))]
    (if (and host (some? ctx))
      (let [{:keys [config update-config pending trigger-turn clear-history]} ctx
            {:keys [enabled backend lg-backend endpoint model scenario auto-approve interval-ms
                    voice-enabled voice-id voice-speed comfy-enabled comfy-endpoint comfy-workflow
                    comfy-steps comfy-width comfy-height comfy-batch-size comfy-cfg
                    comfy-sampler-name comfy-scheduler]} config]
        ($ :.ai-dm
          ($ :header
            ($ :h2 "AI Dungeon Master")
            (if enabled
              ($ :span.ai-dm-status {:data-active true}
                (if pending "Thinking..." "Active"))
              ($ :span.ai-dm-status {:data-active false} "Disabled")))

          ($ :fieldset.ai-dm-fields
            ;; Enable toggle
            ($ field-row {:label "Enable AI DM"}
              ($ :input {:type "checkbox"
                         :checked (boolean enabled)
                         :on-change #(update-config
                                       (fn [c] (assoc c :enabled (not enabled))))}))

            ;; Optional image generation toggle (always visible)
            ($ field-row {:label "Enable narration images"}
              ($ :input {:type "checkbox"
                         :checked (boolean comfy-enabled)
                         :on-change #(update-config
                                       (fn [c] (assoc c :comfy-enabled (not comfy-enabled))))}))

            ;; Backend
            ($ field-row {:label "Backend"}
              ($ :select
                {:value (name backend)
                 :on-change #(update-config
                               (fn [c] (assoc c :backend (keyword (.. % -target -value)))))}
                ($ :option {:value "ollama"}    "Ollama (local, direct)")
                ($ :option {:value "grok"}      "Grok (xAI, direct)")
                ($ :option {:value "langgraph"} "LangGraph sidecar (multi-step)")))

            ;; LangGraph LLM backend
            (when (= backend :langgraph)
              ($ field-row {:label "Sidecar LLM backend"}
                ($ :select
                  {:value (name (or lg-backend :ollama))
                   :on-change #(let [next-backend (keyword (.. % -target -value))]
                                 (update-config
                                   (fn [c]
                                     (cond-> (assoc c :lg-backend next-backend)
                                       (and (= next-backend :grok)
                                            (= (:model c) "qwen2.5:14b-instruct-q4_K_M"))
                                       (assoc :model "")))))}
                  ($ :option {:value "ollama"} "Ollama")
                  ($ :option {:value "grok"}   "Grok (xAI)"))))

            ;; Ollama endpoint
            (when (or (= backend :ollama)
                      (and (= backend :langgraph) (= (or lg-backend :ollama) :ollama)))
              ($ field-row {:label "Ollama endpoint"}
                ($ :input.text
                  {:type "text"
                   :value (or endpoint "")
                   :placeholder "http://localhost:11434"
                   :on-change #(update-config
                                 (fn [c] (assoc c :endpoint (.. % -target -value))))})))

            ;; LangGraph sidecar endpoint
            (when (= backend :langgraph)
              ($ field-row {:label "Sidecar URL"}
                ($ :input.text
                  {:type "text"
                   :value (or (:lg-endpoint config) "")
                   :placeholder "http://localhost:8765"
                   :on-change #(update-config
                                 (fn [c] (assoc c :lg-endpoint (.. % -target -value))))})))

            ;; ComfyUI endpoint (sidecar image generation)
            (when (= backend :langgraph)
              ;; ComfyUI endpoint (sidecar image generation)
              ($ field-row {:label "ComfyUI URL"}
                ($ :input.text
                  {:type "text"
                   :value (or comfy-endpoint "")
                   :placeholder "http://127.0.0.1:8188"
                   :on-change #(update-config
                                 (fn [c] (assoc c :comfy-endpoint (.. % -target -value))))}))

              ($ field-row {:label "Comfy preset"}
                ($ :div {:style {:display "flex" :gap "6px"}}
                  ($ :button.button.button-neutral
                    {:type "button"
                     :on-click #(update-config comfy-preset-12gb-fast)}
                    "12GB Fast")
                  ($ :button.button.button-neutral
                    {:type "button"
                     :on-click #(update-config comfy-preset-12gb-quality)}
                    "12GB Quality")))

              ($ field-row {:label "Comfy steps"}
                ($ :input.text
                  {:type "number"
                   :min 4
                   :max 80
                   :value (or comfy-steps 16)
                   :on-change #(update-config
                                 (fn [c] (assoc c :comfy-steps
                                           (parse-int-safe (.. % -target -value) (or (:comfy-steps c) 16)) )))}))

              ($ field-row {:label "Comfy width"}
                ($ :input.text
                  {:type "number"
                   :min 256
                   :max 2048
                   :step 64
                   :value (or comfy-width 832)
                   :on-change #(update-config
                                 (fn [c] (assoc c :comfy-width
                                           (parse-int-safe (.. % -target -value) (or (:comfy-width c) 832)) )))}))

              ($ field-row {:label "Comfy height"}
                ($ :input.text
                  {:type "number"
                   :min 256
                   :max 2048
                   :step 64
                   :value (or comfy-height 512)
                   :on-change #(update-config
                                 (fn [c] (assoc c :comfy-height
                                           (parse-int-safe (.. % -target -value) (or (:comfy-height c) 512)) )))}))

              ($ field-row {:label "Comfy batch size"}
                ($ :input.text
                  {:type "number"
                   :min 1
                   :max 4
                   :value (or comfy-batch-size 1)
                   :on-change #(update-config
                                 (fn [c] (assoc c :comfy-batch-size
                                           (parse-int-safe (.. % -target -value) (or (:comfy-batch-size c) 1)) )))}))

              ($ field-row {:label "Comfy CFG"}
                ($ :input.text
                  {:type "number"
                   :min 1
                   :max 20
                   :step 0.1
                   :value (or comfy-cfg 3.2)
                   :on-change #(update-config
                                 (fn [c] (assoc c :comfy-cfg
                                           (parse-float-safe (.. % -target -value) (or (:comfy-cfg c) 3.2)) )))}))

              ($ field-row {:label "Comfy sampler"}
                ($ :input.text
                  {:type "text"
                   :value (or comfy-sampler-name "euler")
                   :placeholder "euler"
                   :on-change #(update-config
                                 (fn [c] (assoc c :comfy-sampler-name
                                           (.. % -target -value))))}))

              ($ field-row {:label "Comfy scheduler"}
                ($ :input.text
                  {:type "text"
                   :value (or comfy-scheduler "normal")
                   :placeholder "normal"
                   :on-change #(update-config
                                 (fn [c] (assoc c :comfy-scheduler
                                           (.. % -target -value))))}))

              ;; ComfyUI workflow graph JSON (used by DM Narration Generate art action)
              ($ field-row {:label "Comfy workflow JSON"}
                ($ :textarea.text
                  {:rows 6
                   :value (or comfy-workflow "")
                   :placeholder "{\"3\":{\"inputs\":{...},\"class_type\":\"KSampler\"}, ... }"
                   :on-change #(update-config
                                 (fn [c] (assoc c :comfy-workflow (.. % -target -value))))})))

            ;; Grok API key
            (when (or (= backend :grok)
                      (and (= backend :langgraph) (= (or lg-backend :ollama) :grok)))
              ($ field-row {:label "Grok API key"}
                ($ :input.text
                  {:type "password"
                   :value (or api-key "")
                   :placeholder "xai-..."
                   :on-change (fn [e]
                                (let [v (.. e -target -value)]
                                  (set-api-key v)
                                  (.setItem js/localStorage "ai-dm-api-key" v)))})))

            ;; Model
            ($ field-row {:label "Model"}
              ($ :input.text
                {:type "text"
                 :value (or model "")
                 :placeholder
                 (let [active-backend (if (= backend :langgraph)
                                        (or lg-backend :ollama)
                                        backend)]
                   (if (= active-backend :grok)
                     (if (= backend :langgraph)
                       "grok-3-mini (blank = .env.local)"
                       "grok-3-mini")
                     "llama3.1"))
                 :on-change #(update-config
                               (fn [c] (assoc c :model (.. % -target -value))))}))

            ;; Scenario
            ($ field-row {:label "Scenario"}
              ($ :textarea.text
                {:rows 4
                 :value (or scenario "")
                 :placeholder "Dark dungeon crawl, 4 level-3 adventurers..."
                 :on-change #(update-config
                               (fn [c] (assoc c :scenario (.. % -target -value))))}))

            ;; Auto-approve
            ($ field-row {:label "Auto-approve actions"}
              ($ :input {:type "checkbox"
                         :checked (boolean auto-approve)
                         :on-change #(update-config
                                       (fn [c] (assoc c :auto-approve (not auto-approve))))}))

            ;; Voice narration
            ($ field-row {:label "Voice narration"}
              ($ :input {:type "checkbox"
                         :checked (boolean voice-enabled)
                         :on-change #(update-config
                                       (fn [c] (assoc c :voice-enabled (not voice-enabled))))}))

            (when voice-enabled
              ($ field-row {:label "Voice"}
                ($ :select
                  {:value (or voice-id "bm_george")
                   :on-change #(update-config
                                 (fn [c] (assoc c :voice-id (.. % -target -value))))}
                  ($ :option {:value "bm_george"} "George (British male) ★")
                  ($ :option {:value "bm_lewis"}  "Lewis (British male)")
                  ($ :option {:value "am_adam"}   "Adam (American male)")
                  ($ :option {:value "am_echo"}   "Echo (American male)")
                  ($ :option {:value "af_sky"}    "Sky (American female)")
                  ($ :option {:value "af_nova"}   "Nova (American female)")
                  ($ :option {:value "bf_emma"}   "Emma (British female)"))))

            (when voice-enabled
              ($ field-row {:label (str "Speed (" (or voice-speed 0.95) "×)")}
                ($ :input {:type "range"
                            :min 0.7 :max 1.3 :step 0.05
                            :value (or voice-speed 0.95)
                            :on-change #(update-config
                                          (fn [c] (assoc c :voice-speed
                                                    (js/parseFloat (.. % -target -value)))))})))

            ;; Interval
            ($ field-row {:label (str "Turn interval (" (/ interval-ms 1000) "s)")}
              ($ :input {:type "range"
                         :min 5000 :max 600000 :step 5000
                         :value interval-ms
                         :on-change #(update-config
                                       (fn [c] (assoc c :interval-ms
                                                 (js/parseInt (.. % -target -value)))))})))

          ($ :p.ai-dm-help
            (case backend
              :ollama    "Ensure Ollama is running with OLLAMA_ORIGINS=* for CORS support."
              :grok      "Your API key is stored in this browser only and never sent to the OgresVTT server."
              :langgraph "Start the sidecar: uvicorn ai_dm.main:app --port 8765 --reload. In Grok mode, leave Model blank to use .env.local defaults. Turn on narration images and configure Comfy workflow JSON. Images are generated automatically after AI DM narration using a LangGraph prompt-transform node. Default Comfy tuning targets 12GB VRAM (16 steps, 832x512, batch 1)."
              ""))))
      ;; Non-host or context not available
      ($ :.ai-dm
        ($ :header ($ :h2 "AI Dungeon Master"))
        ($ :p "Only the session host can configure the AI Dungeon Master.")))))

(defui ^:memo actions []
  (let [result (hooks/use-query query)
        {:keys [user/host]} result
        ctx (uix/use-context ai/context)]
    (when (and host (some? ctx))
      (let [{:keys [config pending trigger-turn clear-history]} ctx
            {:keys [enabled]} config]
        ($ :<>
          ($ :button.button.button-neutral
            {:disabled (or (not enabled) pending)
             :on-click trigger-turn}
            ($ icon {:name "play-fill" :size 16})
            (if pending "Running..." "Run turn"))
          ($ :button.button.button-neutral
            {:on-click clear-history}
            "Clear history"))))))
