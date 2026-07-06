import { useEffect } from "react";
import { EMOTIONS, type Emotion } from "../types";

const portraitUrl = (emotion: Emotion) => `/character/${emotion}.svg`;

/**
 * 立ち絵表示(docs/05 §1.3)。
 * フェーズ1では静止画差分。将来 Live2D 等に差し替えられるよう表示部はこの
 * コンポーネントに閉じ込めておく。
 */
export default function CharacterView({ emotion, busy }: { emotion: Emotion; busy: boolean }) {
  // 表情切替時のちらつき防止に全差分を先読みする
  useEffect(() => {
    for (const e of EMOTIONS) {
      const img = new Image();
      img.src = portraitUrl(e);
    }
  }, []);

  return (
    <aside className="character-pane">
      <div className={`character-stage ${busy ? "is-busy" : ""}`}>
        <img key={emotion} src={portraitUrl(emotion)} alt="紫桜" className="portrait" />
      </div>
      <div className="nameplate">
        <span className="nameplate-name">紫桜</span>
        <span className="nameplate-status">{busy ? "考え中…" : "オンライン"}</span>
      </div>
    </aside>
  );
}
