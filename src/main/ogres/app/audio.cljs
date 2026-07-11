(ns ogres.app.audio
  "Procedurally generated ambience and sound effects via the Web Audio API.
   No audio assets are required: every mood and effect is synthesized from
   oscillators and filtered noise. Safe to load outside the browser (all
   browser APIs are touched lazily and guarded)."
  (:require [clojure.string :as str]))

(def ^:private storage-key "ogres-audio")

(def ambience-moods
  ["none" "dungeon" "cave" "forest" "tavern" "battle" "storm" "mystic" "calm"])

(def sound-effects
  ["sword_clash" "arrow_whoosh" "magic_cast" "fireball" "door_creak"
   "thunder" "monster_roar" "coins" "dice_roll" "heal" "victory_fanfare"
   "damage_hit" "death_knell"])

(defn ^:private browser? []
  (and (exists? js/window) (exists? js/document)))

(defn ^:private audio-supported? []
  (and (browser?)
       (or (exists? js/AudioContext)
           (exists? js/webkitAudioContext))))

(defn ^:private load-settings []
  (or (when (and (browser?) (exists? js/localStorage))
        (try
          (when-let [raw (.getItem js/localStorage storage-key)]
            (js->clj (js/JSON.parse raw) :keywordize-keys true))
          (catch :default _ nil)))
      {}))

(defonce state
  (atom (merge {:enabled false :volume 0.6 :mood "none"}
               (select-keys (load-settings) [:enabled :volume :mood]))))

(defn ^:private save-settings! []
  (when (and (browser?) (exists? js/localStorage))
    (try
      (.setItem js/localStorage storage-key
                (js/JSON.stringify (clj->js (select-keys @state [:enabled :volume :mood]))))
      (catch :default _ nil))))

;; ---------------------------------------------------------------------------
;; Audio context and helpers
;; ---------------------------------------------------------------------------

(defonce ^:private ctx-ref (atom nil))
(defonce ^:private master-ref (atom nil))
;; {:nodes [...] :timers [...]} for the currently playing ambience layer.
(defonce ^:private ambience-ref (atom nil))

(defn ^:private ensure-context!
  "Lazily creates the shared AudioContext and master gain. Registers a
   one-time pointer listener to resume the context if the browser suspends
   it under its autoplay policy."
  []
  (when (audio-supported?)
    (when (nil? @ctx-ref)
      (let [Ctor (if (exists? js/AudioContext) js/AudioContext js/webkitAudioContext)
            ctx  (Ctor.)
            gn   (.createGain ctx)]
        (set! (.. gn -gain -value) (:volume @state))
        (.connect gn (.-destination ctx))
        (reset! ctx-ref ctx)
        (reset! master-ref gn)
        (.addEventListener js/document "pointerdown"
          (fn resume []
            (when (= (.-state ctx) "suspended")
              (.resume ctx)))
          #js {"passive" true})))
    (let [ctx @ctx-ref]
      (when (= (.-state ctx) "suspended")
        (.resume ctx))
      ctx)))

(defn ^:private noise-buffer
  "Returns a looping AudioBuffer of noise. `color` is :white or :brown."
  [ctx color]
  (let [len (* 2 (.-sampleRate ctx))
        buf (.createBuffer ctx 1 len (.-sampleRate ctx))
        chn (.getChannelData buf 0)]
    (case color
      :brown
      (loop [i 0 last 0]
        (when (< i len)
          (let [white (- (* 2 (js/Math.random)) 1)
                next  (/ (+ last (* 0.02 white)) 1.02)]
            (aset chn i (* next 3.5))
            (recur (inc i) next))))
      (dotimes [i len]
        (aset chn i (- (* 2 (js/Math.random)) 1))))
    buf))

(defn ^:private noise-src [ctx color]
  (let [src (.createBufferSource ctx)]
    (set! (.-buffer src) (noise-buffer ctx color))
    (set! (.-loop src) true)
    src))

(defn ^:private osc [ctx type freq]
  (let [o (.createOscillator ctx)]
    (set! (.-type o) type)
    (set! (.. o -frequency -value) freq)
    o))

(defn ^:private gain-node [ctx v]
  (let [g (.createGain ctx)]
    (set! (.. g -gain -value) v)
    g))

(defn ^:private filt [ctx type freq & [q]]
  (let [f (.createBiquadFilter ctx)]
    (set! (.-type f) type)
    (set! (.. f -frequency -value) freq)
    (when q (set! (.. f -Q -value) q))
    f))

(defn ^:private chain
  "Connects nodes in order, ending at the master gain. Returns the nodes."
  [nodes]
  (doseq [[a b] (partition 2 1 nodes)]
    (.connect a b))
  (.connect (last nodes) @master-ref)
  nodes)

(defn ^:private lfo
  "Attaches a low-frequency oscillator to the given AudioParam.
   Returns the oscillator (already started)."
  [ctx param freq depth]
  (let [o (osc ctx "sine" freq)
        g (gain-node ctx depth)]
    (.connect o g)
    (.connect g param)
    (.start o)
    o))

;; ---------------------------------------------------------------------------
;; One-shot effect primitives
;; ---------------------------------------------------------------------------

(defn ^:private blip!
  "Plays a single enveloped oscillator sweep. All times are in seconds
   relative to now."
  [ctx {:keys [type f0 f1 dur vol delay curve]
        :or {type "sine" f1 nil dur 0.3 vol 0.3 delay 0 curve 0.015}}]
  (let [t0 (+ (.-currentTime ctx) delay)
        o  (osc ctx type f0)
        g  (gain-node ctx 0)]
    (chain [o g])
    (.setValueAtTime (.-gain g) 0 t0)
    (.linearRampToValueAtTime (.-gain g) vol (+ t0 curve))
    (.exponentialRampToValueAtTime (.-gain g) 0.0001 (+ t0 dur))
    (when f1
      (.setValueAtTime (.-frequency o) f0 t0)
      (.exponentialRampToValueAtTime (.-frequency o) f1 (+ t0 dur)))
    (.start o t0)
    (.stop o (+ t0 dur 0.05))))

(defn ^:private noise-burst!
  "Plays a filtered noise burst."
  [ctx {:keys [color ftype freq q dur vol delay f1]
        :or {color :white ftype "bandpass" freq 1000 q 1 dur 0.2 vol 0.3 delay 0}}]
  (let [t0  (+ (.-currentTime ctx) delay)
        src (noise-src ctx color)
        f   (filt ctx ftype freq q)
        g   (gain-node ctx 0)]
    (chain [src f g])
    (.setValueAtTime (.-gain g) 0 t0)
    (.linearRampToValueAtTime (.-gain g) vol (+ t0 0.01))
    (.exponentialRampToValueAtTime (.-gain g) 0.0001 (+ t0 dur))
    (when f1
      (.setValueAtTime (.-frequency f) freq t0)
      (.exponentialRampToValueAtTime (.-frequency f) f1 (+ t0 dur)))
    (.start src t0)
    (.stop src (+ t0 dur 0.05))))

;; ---------------------------------------------------------------------------
;; Sound effects
;; ---------------------------------------------------------------------------

(defn ^:private play-effect* [ctx effect]
  (case effect
    "sword_clash"
    (do (noise-burst! ctx {:freq 3200 :q 2 :dur 0.18 :vol 0.35})
        (blip! ctx {:f0 2500 :f1 1800 :dur 0.22 :vol 0.18 :type "triangle"}))
    "arrow_whoosh"
    (noise-burst! ctx {:freq 500 :f1 2400 :q 3 :dur 0.32 :vol 0.3})
    "magic_cast"
    (do (blip! ctx {:f0 300 :f1 1400 :dur 0.5 :vol 0.22 :type "sine"})
        (blip! ctx {:f0 1600 :f1 2400 :dur 0.4 :vol 0.1 :delay 0.15 :type "triangle"}))
    "fireball"
    (do (noise-burst! ctx {:color :brown :ftype "lowpass" :freq 2200 :f1 200 :dur 0.9 :vol 0.5})
        (blip! ctx {:f0 220 :f1 60 :dur 0.7 :vol 0.25 :type "sawtooth"}))
    "door_creak"
    (do (blip! ctx {:f0 90 :f1 150 :dur 0.8 :vol 0.16 :type "sawtooth" :curve 0.3})
        (blip! ctx {:f0 60 :f1 45 :dur 0.35 :vol 0.3 :delay 0.75}))
    "thunder"
    (noise-burst! ctx {:color :brown :ftype "lowpass" :freq 400 :f1 90 :dur 2.2 :vol 0.55})
    "monster_roar"
    (do (blip! ctx {:f0 110 :f1 45 :dur 1.0 :vol 0.4 :type "sawtooth" :curve 0.08})
        (noise-burst! ctx {:color :brown :ftype "lowpass" :freq 700 :f1 150 :dur 1.0 :vol 0.3}))
    "coins"
    (dotimes [i 4]
      (blip! ctx {:f0 (+ 2200 (* 400 (js/Math.random))) :dur 0.12 :vol 0.14
                  :delay (* i 0.07) :type "triangle"}))
    "dice_roll"
    (dotimes [i 6]
      (noise-burst! ctx {:freq (+ 1800 (* 900 (js/Math.random))) :q 6 :dur 0.05 :vol 0.2
                         :delay (+ (* i 0.09) (* 0.03 (js/Math.random)))}))
    "heal"
    (doseq [[i f] (map-indexed vector [440 554 659])]
      (blip! ctx {:f0 f :dur 0.4 :vol 0.14 :delay (* i 0.12) :type "triangle"}))
    "victory_fanfare"
    (doseq [[i f] (map-indexed vector [523 659 784 1046])]
      (blip! ctx {:f0 f :dur (if (= f 1046) 0.7 0.25) :vol 0.16 :delay (* i 0.16) :type "square"}))
    "damage_hit"
    (do (blip! ctx {:f0 160 :f1 55 :dur 0.25 :vol 0.4})
        (noise-burst! ctx {:freq 900 :dur 0.12 :vol 0.2}))
    "death_knell"
    (do (blip! ctx {:f0 110 :f1 55 :dur 1.4 :vol 0.3 :curve 0.05})
        (blip! ctx {:f0 165 :f1 82 :dur 1.4 :vol 0.15 :delay 0.05 :curve 0.05}))
    nil))

;; ---------------------------------------------------------------------------
;; Ambience moods
;; ---------------------------------------------------------------------------

(defn ^:private start-node! [n] (.start n) n)

(defn ^:private drone
  "Looping filtered-noise bed. Returns started nodes."
  [ctx {:keys [color ftype freq q vol lfo-rate lfo-depth]
        :or {color :brown ftype "lowpass" q 0.8 lfo-rate 0.1 lfo-depth 0}}]
  (let [src (noise-src ctx color)
        f   (filt ctx ftype freq q)
        g   (gain-node ctx vol)]
    (chain [src f g])
    (cond-> [(start-node! src) f g]
      (pos? lfo-depth) (conj (lfo ctx (.-gain g) lfo-rate lfo-depth)))))

(defn ^:private pad
  "Sustained oscillator tone with optional shimmer LFO."
  [ctx {:keys [type freq vol lfo-rate lfo-depth detune]
        :or {type "sine" lfo-rate 0.15 lfo-depth 0 detune 0}}]
  (let [o (osc ctx type freq)
        g (gain-node ctx vol)]
    (when (pos? detune) (set! (.. o -detune -value) detune))
    (chain [o g])
    (cond-> [(start-node! o) g]
      (pos? lfo-depth) (conj (lfo ctx (.-gain g) lfo-rate lfo-depth)))))

(defn ^:private every-ms
  "Runs f on a randomized interval between min-ms and max-ms.
   Returns a timer handle vector."
  [f min-ms max-ms]
  (let [id (js/setInterval
            (fn [] (when (< (js/Math.random) 0.55) (f)))
            (+ min-ms (* (js/Math.random) (- max-ms min-ms))))]
    [id]))

(defn ^:private build-mood [ctx mood]
  (case mood
    "dungeon"
    {:nodes (concat (drone ctx {:freq 220 :vol 0.28 :lfo-rate 0.07 :lfo-depth 0.08})
                    (pad ctx {:freq 55 :vol 0.05 :lfo-rate 0.05 :lfo-depth 0.02}))
     :timers (every-ms
              #(blip! ctx {:f0 1200 :f1 400 :dur 0.25 :vol 0.06})
              3000 9000)}
    "cave"
    {:nodes (concat (drone ctx {:freq 150 :vol 0.3 :lfo-rate 0.05 :lfo-depth 0.1})
                    (pad ctx {:freq 41 :vol 0.06 :lfo-rate 0.04 :lfo-depth 0.02}))
     :timers (every-ms
              (fn []
                (blip! ctx {:f0 1400 :f1 500 :dur 0.3 :vol 0.05})
                (blip! ctx {:f0 1000 :f1 380 :dur 0.4 :vol 0.03 :delay 0.35}))
              4000 12000)}
    "forest"
    {:nodes (drone ctx {:color :white :ftype "bandpass" :freq 500 :q 0.5 :vol 0.06
                        :lfo-rate 0.12 :lfo-depth 0.03})
     :timers (every-ms
              (fn []
                (dotimes [i (inc (rand-int 3))]
                  (blip! ctx {:f0 (+ 2400 (* 800 (js/Math.random)))
                              :f1 (+ 1800 (* 600 (js/Math.random)))
                              :dur 0.12 :vol 0.05 :delay (* i 0.15) :type "sine"})))
              2500 8000)}
    "tavern"
    {:nodes (drone ctx {:ftype "bandpass" :freq 320 :q 0.7 :vol 0.22
                        :lfo-rate 0.9 :lfo-depth 0.06})
     :timers (concat
              (every-ms #(blip! ctx {:f0 (+ 1800 (* 600 (js/Math.random))) :dur 0.1 :vol 0.05
                                     :type "triangle"})
                        3000 9000)
              (every-ms #(blip! ctx {:f0 260 :f1 320 :dur 0.3 :vol 0.04 :type "sine"})
                        5000 14000))}
    "battle"
    {:nodes (concat (drone ctx {:freq 400 :vol 0.14 :lfo-rate 0.4 :lfo-depth 0.05})
                    (pad ctx {:type "sawtooth" :freq 49 :vol 0.04 :lfo-rate 0.3 :lfo-depth 0.02}))
     :timers (concat
              [(js/setInterval
                (fn []
                  (blip! ctx {:f0 100 :f1 40 :dur 0.3 :vol 0.3})
                  (when (< (js/Math.random) 0.5)
                    (blip! ctx {:f0 90 :f1 38 :dur 0.25 :vol 0.22 :delay 0.35})))
                900)]
              (every-ms #(noise-burst! ctx {:freq 2600 :q 2 :dur 0.12 :vol 0.08})
                        2000 6000))}
    "storm"
    {:nodes (concat (drone ctx {:color :white :ftype "highpass" :freq 1200 :vol 0.12})
                    (drone ctx {:freq 260 :vol 0.2 :lfo-rate 0.09 :lfo-depth 0.08}))
     :timers (every-ms
              #(noise-burst! ctx {:color :brown :ftype "lowpass" :freq 350 :f1 80
                                  :dur (+ 1.2 (js/Math.random)) :vol 0.35})
              8000 20000)}
    "mystic"
    {:nodes (concat (pad ctx {:freq 110 :vol 0.05 :lfo-rate 0.11 :lfo-depth 0.03})
                    (pad ctx {:freq 165 :vol 0.04 :lfo-rate 0.13 :lfo-depth 0.025 :detune 6})
                    (pad ctx {:freq 220 :vol 0.03 :lfo-rate 0.17 :lfo-depth 0.02 :detune -5}))
     :timers (every-ms
              #(blip! ctx {:f0 (rand-nth [880 1100 1320]) :dur 1.2 :vol 0.05
                           :type "triangle" :curve 0.2})
              4000 11000)}
    "calm"
    {:nodes (concat (pad ctx {:type "triangle" :freq 220 :vol 0.035 :lfo-rate 0.08 :lfo-depth 0.015})
                    (pad ctx {:type "triangle" :freq 330 :vol 0.025 :lfo-rate 0.1 :lfo-depth 0.012})
                    (drone ctx {:ftype "bandpass" :freq 450 :q 0.4 :vol 0.04
                                :lfo-rate 0.07 :lfo-depth 0.02}))
     :timers []}
    nil))

(defn ^:private stop-ambience! []
  (when-let [{:keys [nodes timers]} @ambience-ref]
    (doseq [t timers] (js/clearInterval t))
    (doseq [n nodes]
      (try
        (when (.-stop n) (.stop n))
        (catch :default _ nil))
      (try (.disconnect n) (catch :default _ nil)))
    (reset! ambience-ref nil)))

;; ---------------------------------------------------------------------------
;; Public API
;; ---------------------------------------------------------------------------

(defn set-volume!
  "Sets master volume, 0.0–1.0."
  [v]
  (let [v (-> v (max 0) (min 1))]
    (swap! state assoc :volume v)
    (save-settings!)
    (when-let [g @master-ref]
      (.setTargetAtTime (.-gain g) v (.-currentTime @ctx-ref) 0.05))
    {:ok true :volume v}))

(defn set-ambience!
  "Switches the looping ambient soundscape. Pass \"none\" to stop.
   The requested mood is remembered even while audio is disabled."
  [mood]
  (let [mood (if (some #{mood} ambience-moods) mood "none")]
    (swap! state assoc :mood mood)
    (save-settings!)
    (cond
      (not (audio-supported?))
      {:ok true :note "Audio not supported in this environment."}
      (not (:enabled @state))
      {:ok true :note "Soundscape saved; audio is disabled in the AI DM panel."}
      :else
      (let [ctx (ensure-context!)]
        (stop-ambience!)
        (when-let [layer (build-mood ctx mood)]
          (reset! ambience-ref layer))
        {:ok true :mood mood}))))

(defn play-effect!
  "Plays a one-shot synthesized sound effect by name."
  [effect]
  (cond
    (not (some #{effect} sound-effects))
    {:ok false :reason (str "Unknown sound effect: " effect
                            ". Valid: " (pr-str sound-effects))}
    (not (audio-supported?))
    {:ok true :note "Audio not supported in this environment."}
    (not (:enabled @state))
    {:ok true :note "Sound skipped; audio is disabled in the AI DM panel."}
    :else
    (do (play-effect* (ensure-context!) effect)
        {:ok true :effect effect})))

(defn set-enabled!
  "Enables or disables all generated audio. Enabling restarts the most
   recently requested ambience mood."
  [enabled?]
  (swap! state assoc :enabled (boolean enabled?))
  (save-settings!)
  (if enabled?
    (set-ambience! (:mood @state))
    (stop-ambience!))
  {:ok true :enabled (boolean enabled?)})

(defn effect-label
  "Human-readable label for a sound effect id, e.g. \"sword_clash\" -> \"Sword clash\"."
  [effect]
  (let [s (str/replace (or effect "") "_" " ")]
    (if (seq s)
      (str (.toUpperCase (subs s 0 1)) (subs s 1))
      s)))
