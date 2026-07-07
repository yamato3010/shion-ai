import { Suspense, lazy, useEffect, useState } from "react";
import { EMOTIONS, type Emotion } from "../types";

// VRMレンダラ(three.js)は重いので、model.vrm があるときだけ動的ロードする
const VrmRenderer = lazy(() => import("./VrmRenderer"));

const portraitUrl = (emotion: Emotion) => `/character/${emotion}.svg`;

type RenderMode = "detecting" | "vrm" | "static";

// カメラ設定(距離・上下)。好みはlocalStorageに保存してリロード後も維持する
const DISTANCE_KEY = "shion-vrm-distance";
const DISTANCE_MIN = 0.6;
const DISTANCE_MAX = 3.5;
const DISTANCE_STEP = 0.25;
const DISTANCE_DEFAULT = 1.45;

const HEIGHT_KEY = "shion-vrm-height";
const HEIGHT_MIN = -0.8;
const HEIGHT_MAX = 0.8;
const HEIGHT_STEP = 0.08;
const HEIGHT_DEFAULT = 0;

function loadStored(key: string, min: number, max: number, fallback: number): number {
  const raw = Number(localStorage.getItem(key));
  if (Number.isFinite(raw) && raw >= min && raw <= max) return raw;
  return fallback;
}

/**
 * 立ち絵表示(docs/05 §1.3)。
 * frontend/public/character/model.vrm を置くとVRM立ち絵(まばたき・表情・口パク)、
 * 無ければ静止画差分(7種SVG)で表示する。レンダラ差し替えはこのコンポーネントに閉じる。
 */
export default function CharacterView({
  emotion,
  busy,
  speaking = false,
}: {
  emotion: Emotion;
  busy: boolean;
  speaking?: boolean;
}) {
  const [mode, setMode] = useState<RenderMode>("detecting");
  const [showCameraPanel, setShowCameraPanel] = useState(false);
  const [distance, setDistance] = useState(() =>
    loadStored(DISTANCE_KEY, DISTANCE_MIN, DISTANCE_MAX, DISTANCE_DEFAULT),
  );
  const [height, setHeight] = useState(() =>
    loadStored(HEIGHT_KEY, HEIGHT_MIN, HEIGHT_MAX, HEIGHT_DEFAULT),
  );

  const adjustDistance = (delta: number) => {
    setDistance((prev) => {
      const next = Math.min(DISTANCE_MAX, Math.max(DISTANCE_MIN, +(prev + delta).toFixed(2)));
      localStorage.setItem(DISTANCE_KEY, String(next));
      return next;
    });
  };

  const adjustHeight = (delta: number) => {
    setHeight((prev) => {
      const next = Math.min(HEIGHT_MAX, Math.max(HEIGHT_MIN, +(prev + delta).toFixed(2)));
      localStorage.setItem(HEIGHT_KEY, String(next));
      return next;
    });
  };

  const resetCamera = () => {
    localStorage.removeItem(DISTANCE_KEY);
    localStorage.removeItem(HEIGHT_KEY);
    setDistance(DISTANCE_DEFAULT);
    setHeight(HEIGHT_DEFAULT);
  };

  useEffect(() => {
    fetch("/character/model.vrm", { method: "HEAD" })
      .then((res) => {
        // 開発サーバーはSPAフォールバックでHTMLを返すことがあるためcontent-typeも見る
        const type = res.headers.get("content-type") ?? "";
        setMode(res.ok && !type.includes("text/html") ? "vrm" : "static");
      })
      .catch(() => setMode("static"));
  }, []);

  // 表情切替時のちらつき防止に静止画差分を先読みする
  useEffect(() => {
    if (mode !== "static") return;
    for (const e of EMOTIONS) {
      const img = new Image();
      img.src = portraitUrl(e);
    }
  }, [mode]);

  const staticPortrait = (
    <img key={emotion} src={portraitUrl(emotion)} alt="紫桜" className="portrait" />
  );

  return (
    <aside className="character-pane">
      <div className={`character-stage ${busy ? "is-busy" : ""}`}>
        {mode === "vrm" ? (
          <>
            <Suspense fallback={staticPortrait}>
              <VrmRenderer
                emotion={emotion}
                speaking={speaking}
                distance={distance}
                heightOffset={height}
                onError={() => setMode("static")}
              />
            </Suspense>
            <div className="vrm-controls">
              {showCameraPanel && (
                <div className="vrm-camera-panel">
                  <button
                    title="近づく"
                    onClick={() => adjustDistance(-DISTANCE_STEP)}
                    disabled={distance <= DISTANCE_MIN}
                  >
                    ➕
                  </button>
                  <button
                    title="離れる"
                    onClick={() => adjustDistance(DISTANCE_STEP)}
                    disabled={distance >= DISTANCE_MAX}
                  >
                    ➖
                  </button>
                  <button
                    title="視点を上へ"
                    onClick={() => adjustHeight(HEIGHT_STEP)}
                    disabled={height >= HEIGHT_MAX}
                  >
                    ⬆
                  </button>
                  <button
                    title="視点を下へ"
                    onClick={() => adjustHeight(-HEIGHT_STEP)}
                    disabled={height <= HEIGHT_MIN}
                  >
                    ⬇
                  </button>
                  <button title="初期位置に戻す" onClick={resetCamera}>
                    ↺
                  </button>
                </div>
              )}
              <button
                className={`vrm-gear ${showCameraPanel ? "is-open" : ""}`}
                title="カメラ調整"
                onClick={() => setShowCameraPanel((v) => !v)}
              >
                ⚙
              </button>
            </div>
          </>
        ) : (
          staticPortrait
        )}
      </div>
      <div className="nameplate">
        <span className="nameplate-name">紫桜</span>
        <span className="nameplate-status">
          {busy ? "考え中…" : speaking ? "お話し中🔊" : "オンライン"}
        </span>
      </div>
    </aside>
  );
}
