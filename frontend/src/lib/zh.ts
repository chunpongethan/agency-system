// Detect whether a string is written in Simplified or Traditional Chinese, so
// mixed content (e.g. a Simplified product name inside the Traditional UI) can be
// tagged with lang="zh-Hans" / "zh-Hant". Browsers + the :lang() CSS then pick the
// matching regional font so each renders with its native glyph forms.
//
// Heuristic: count characters that exist ONLY in one variant (distinct codepoints).
// Characters shared by both (e.g. 香港) don't vote, so a shared-only string returns
// undefined and simply inherits the document language.

const SIMP_ONLY =
  "简体这来时间问题东乐买卖车网户团队单会员务应对长发关联证银财资报计划让转项类数据号页图结认说读语试验质检测万与业个们为红险产优势华国学实宝处备复现电医疗门阶级继续经纪约纳缴费贷账币汇储额织构识轻带书笔终顾龙欢应过还进这运达远违适选";
const TRAD_ONLY =
  "簡體這來時間問題東樂買賣車網戶團隊單會員務應對長發關聯證銀財資報計劃讓轉項類數據號頁圖結認說讀語試驗質檢測萬與業個們為紅險產優勢華國學實寶處備復現電醫療門階級繼續經紀約納繳費貸賬幣匯儲額織構識輕帶書筆終顧龍歡應過還進運達遠違適選";

export function chineseVariant(text: string | null | undefined): "zh-Hans" | "zh-Hant" | undefined {
  if (!text) return undefined;
  let s = 0, t = 0;
  for (const ch of text) {
    if (SIMP_ONLY.includes(ch)) s++;
    else if (TRAD_ONLY.includes(ch)) t++;
  }
  if (s > t) return "zh-Hans";
  if (t > s) return "zh-Hant";
  return undefined;               // no distinguishing chars → inherit document lang
}
