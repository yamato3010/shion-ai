import { useEffect, useRef } from "react";
import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { VRMLoaderPlugin, VRMUtils, type VRM } from "@pixiv/three-vrm";
import type { Emotion } from "../types";

/**
 * VRM立ち絵レンダラ(docs/09 フェーズ4)。
 * frontend/public/character/model.vrm を読み込み、まばたき・呼吸などの
 * アイドルモーション、感情タグに応じた表情、読み上げ中の口パクを行う。
 * 読み込みに失敗したら onError で静止画差分にフォールバックする。
 */

const MODEL_URL = "/character/model.vrm";

// 感情 → VRM表情プリセットの重み。モデルに無い表情は無視される
const EMOTION_EXPRESSIONS: Record<Emotion, Record<string, number>> = {
  normal: {},
  joy: { happy: 1.0 },
  sad: { sad: 0.9 },
  surprised: { surprised: 1.0 },
  troubled: { sad: 0.5, angry: 0.15 },
  shy: { happy: 0.4, sad: 0.15 },
  thinking: { relaxed: 0.5 },
};

const FADEABLE = ["happy", "sad", "angry", "surprised", "relaxed"];

export const DEFAULT_CAMERA_DISTANCE = 1.45;

interface Props {
  emotion: Emotion;
  speaking: boolean;
  /** カメラとモデルの距離(0.6=顔アップ 〜 3.5=全身)。CharacterViewの⚙パネルで調整 */
  distance: number;
  /** カメラの上下オフセット(+で視点が上がる)。CharacterViewの⚙パネルで調整 */
  heightOffset: number;
  onError: () => void;
}

export default function VrmRenderer({ emotion, speaking, distance, heightOffset, onError }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  // アニメーションループから最新値を参照するためrefに写す
  const emotionRef = useRef(emotion);
  const speakingRef = useRef(speaking);
  const distanceRef = useRef(distance);
  const heightRef = useRef(heightOffset);
  const onErrorRef = useRef(onError);
  emotionRef.current = emotion;
  speakingRef.current = speaking;
  distanceRef.current = distance;
  heightRef.current = heightOffset;
  onErrorRef.current = onError;

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    let disposed = false;
    let vrm: VRM | null = null;
    let rafId = 0;

    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true });
    } catch {
      onErrorRef.current(); // WebGL不可の環境
      return;
    }
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    container.appendChild(renderer.domElement);

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(24, 1, 0.1, 20);
    let headY = 1.3; // モデル読み込み後に頭の高さで更新される

    // 距離に応じてフレーミングを決める(近い=顔アップ、遠い=注視点を下げて全身が収まる)。
    // heightOffset はカメラと注視点を同時に上下させる(パン)
    const applyCamera = () => {
      const d = distanceRef.current;
      const y = headY - 0.1 - Math.max(0, d - DEFAULT_CAMERA_DISTANCE) * 0.3 + heightRef.current;
      camera.position.set(0, y, d);
      camera.lookAt(0, y - 0.05, 0);
    };
    applyCamera();

    const keyLight = new THREE.DirectionalLight(0xffffff, 2.4);
    keyLight.position.set(1, 2, 2);
    scene.add(keyLight);
    scene.add(new THREE.AmbientLight(0xffffff, 1.1));

    const resize = () => {
      const w = container.clientWidth || 1;
      const h = container.clientHeight || 1;
      renderer.setSize(w, h);
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
    };
    resize();
    const observer = new ResizeObserver(resize);
    observer.observe(container);

    const loader = new GLTFLoader();
    loader.register((parser) => new VRMLoaderPlugin(parser));
    loader.load(
      MODEL_URL,
      (gltf) => {
        if (disposed) return;
        const loaded = gltf.userData.vrm as VRM | undefined;
        if (!loaded) {
          onErrorRef.current();
          return;
        }
        vrm = loaded;
        VRMUtils.removeUnnecessaryVertices(gltf.scene);
        VRMUtils.combineSkeletons?.(gltf.scene);
        VRMUtils.rotateVRM0(vrm); // VRM0.xモデルは正面が逆向き
        scene.add(vrm.scene);

        // 頭の高さに合わせてフレーミング
        const head = vrm.humanoid?.getNormalizedBoneNode("head");
        if (head) headY = head.getWorldPosition(new THREE.Vector3()).y;

        // Tポーズ解消(腕を下ろす)
        const leftArm = vrm.humanoid?.getNormalizedBoneNode("leftUpperArm");
        const rightArm = vrm.humanoid?.getNormalizedBoneNode("rightUpperArm");
        if (leftArm) leftArm.rotation.z = 1.2;
        if (rightArm) rightArm.rotation.z = -1.2;
      },
      undefined,
      () => {
        if (!disposed) onErrorRef.current();
      },
    );

    const clock = new THREE.Clock();
    const current: Record<string, number> = {};
    let nextBlinkIn = 2 + Math.random() * 3;
    let blinkPhase = -1; // -1: 待機中

    const animate = () => {
      rafId = requestAnimationFrame(animate);
      const delta = clock.getDelta();
      const t = clock.elapsedTime;

      if (vrm) {
        // 呼吸・小さな首の動き(アイドルモーション)
        const spine = vrm.humanoid?.getNormalizedBoneNode("spine");
        if (spine) spine.rotation.z = Math.sin(t * 0.6) * 0.012;
        const neck = vrm.humanoid?.getNormalizedBoneNode("neck");
        if (neck) {
          neck.rotation.x = Math.sin(t * 0.8) * 0.02;
          neck.rotation.y = Math.sin(t * 0.35) * 0.04;
        }

        const expressions = vrm.expressionManager;
        if (expressions) {
          // 表情はなめらかにクロスフェード
          const target = EMOTION_EXPRESSIONS[emotionRef.current] ?? {};
          for (const name of FADEABLE) {
            const goal = target[name] ?? 0;
            const value = (current[name] ?? 0) + (goal - (current[name] ?? 0)) * Math.min(1, delta * 6);
            current[name] = value;
            if (expressions.getExpressionTrackName(name)) expressions.setValue(name, value);
          }
          // まばたき。ニコニコ中(happyが強い)は目がすでに細く、重ねると崩れるため止める
          const smiling = (current["happy"] ?? 0) > 0.3;
          if (smiling && blinkPhase >= 0) {
            blinkPhase = -1; // 笑顔になった瞬間に進行中のまばたきも打ち切る
            if (expressions.getExpressionTrackName("blink")) expressions.setValue("blink", 0);
          }
          nextBlinkIn -= delta;
          if (nextBlinkIn <= 0 && blinkPhase < 0) {
            if (!smiling) blinkPhase = 0;
            nextBlinkIn = 2.5 + Math.random() * 3.5;
          }
          if (blinkPhase >= 0) {
            blinkPhase += delta;
            const v = blinkPhase < 0.1 ? blinkPhase / 0.1 : Math.max(0, 1 - (blinkPhase - 0.1) / 0.1);
            if (expressions.getExpressionTrackName("blink")) expressions.setValue("blink", v);
            if (blinkPhase > 0.2) blinkPhase = -1;
          }
          // 読み上げ中の口パク
          const mouth = speakingRef.current ? Math.abs(Math.sin(t * 9)) * 0.6 : 0;
          if (expressions.getExpressionTrackName("aa")) expressions.setValue("aa", mouth);
        }
        vrm.update(delta);
      }
      applyCamera(); // ➕/➖ボタンの距離変更を毎フレーム反映
      renderer.render(scene, camera);
    };
    animate();

    return () => {
      disposed = true;
      cancelAnimationFrame(rafId);
      observer.disconnect();
      if (vrm) {
        scene.remove(vrm.scene);
        VRMUtils.deepDispose(vrm.scene);
      }
      renderer.dispose();
      renderer.domElement.remove();
    };
  }, []);

  return <div ref={containerRef} className="vrm-stage" />;
}
