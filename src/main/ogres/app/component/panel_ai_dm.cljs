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

(defui ^:memo panel []
  (let [result (hooks/use-query query)
        {:keys [user/host]} result
        ctx (uix/use-context ai/context)]
    (if (and host (some? ctx))
      (let [{:keys [config update-config pending trigger-turn clear-history]} ctx
            {:keys [enabled backend endpoint model scenario auto-approve interval-ms]} config
            [api-key set-api-key] (uix/use-state #(.getItem js/localStorage "ai-dm-api-key"))]
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

            ;; Backend
            ($ field-row {:label "Backend"}
              ($ :select
                {:value (name backend)
                 :on-change #(update-config
                               (fn [c] (assoc c :backend (keyword (.. % -target -value)))))}
                ($ :option {:value "ollama"} "Ollama (local)")
                ($ :option {:value "grok"} "Grok (xAI)")))

            ;; Ollama endpoint
            (when (= backend :ollama)
              ($ field-row {:label "Ollama endpoint"}
                ($ :input.text
                  {:type "text"
                   :value (or endpoint "")
                   :placeholder "http://localhost:11434"
                   :on-change #(update-config
                                 (fn [c] (assoc c :endpoint (.. % -target -value))))})))

            ;; Grok API key
            (when (= backend :grok)
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
                 :placeholder (if (= backend :ollama) "llama3.1" "grok-3-mini")
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

            ;; Interval
            ($ field-row {:label (str "Turn interval (" (/ interval-ms 1000) "s)")}
              ($ :input {:type "range"
                         :min 5000 :max 60000 :step 5000
                         :value interval-ms
                         :on-change #(update-config
                                       (fn [c] (assoc c :interval-ms
                                                 (js/parseInt (.. % -target -value)))))})))

          ($ :p.ai-dm-help
            (case backend
              :ollama "Ensure Ollama is running with OLLAMA_ORIGINS=* for CORS support."
              :grok   "Your API key is stored in this browser only and never sent to the OgresVTT server."
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
