(ns ogres.app.ai.voice
  "Plays AI DM narration audio via the LangGraph sidecar's /dm/speak endpoint.
   Falls back silently if the sidecar is unreachable or TTS is disabled.")

(defonce ^:private audio-queue (atom []))
(defonce ^:private playing?    (atom false))

(defn- play-next! []
  (if-let [[blob resolve] (first @audio-queue)]
    (do
      (reset! playing? true)
      (let [url (js/URL.createObjectURL blob)
            el  (js/Audio. url)]
        (set! (.-onended el)
          (fn []
            (js/URL.revokeObjectURL url)
            (swap! audio-queue rest)
            (reset! playing? false)
            (resolve nil)
            (play-next!)))
        (set! (.-onerror el)
          (fn []
            (js/URL.revokeObjectURL url)
            (swap! audio-queue rest)
            (reset! playing? false)
            (resolve nil)
            (play-next!)))
        (.play el)))
    (reset! playing? false)))

(defn speak!
  "Fetches audio from the sidecar and queues it for playback.
   Returns a js/Promise that resolves when the audio finishes playing."
  [text {:keys [sidecar-url voice speed]
         :or   {sidecar-url "http://localhost:8765"
                voice       "bm_george"
                speed       0.95}}]
  (js/Promise.
    (fn [resolve _reject]
      (-> (js/fetch (str sidecar-url "/dm/speak")
            #js {:method  "POST"
                 :headers #js {"Content-Type" "application/json"}
                 :body    (js/JSON.stringify #js {:text text :voice voice :speed speed})})
          (.then (fn [resp]
                   (if (.-ok resp)
                     (.blob resp)
                     (js/Promise.resolve nil))))
          (.then (fn [blob]
                   (if blob
                     (do
                       (swap! audio-queue conj [blob resolve])
                       (when-not @playing? (play-next!)))
                     (resolve nil))))
          (.catch (fn [_] (resolve nil)))))))

(defn stop!
  "Clears the audio queue."
  []
  (reset! audio-queue [])
  (reset! playing? false))
