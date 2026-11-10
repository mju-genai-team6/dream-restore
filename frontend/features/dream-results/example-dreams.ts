import type { ArtworkKind, Confidence, Dream, Scene } from "./types";

function scene(
  id: string, artwork: ArtworkKind, title: string, place: string,
  description: string, elements: [string, Confidence][],
): Scene {
  return {
    id, artwork, imageStatus: "succeeded",
    versions: [{
      version: 1, title, place, description, createdAt: "2026-11-08T07:30:00+09:00",
      elements: elements.map(([name, confidence], index) => ({ id: `${id}-element-${index}`, name, confidence })),
    }],
  };
}

// 실제 꿈 기록이 아닌 화면 개발용 데이터입니다.
export const exampleDreams: Dream[] = [
  {
    id: "demo-seaside", title: "학교에서 바다로 이어진 꿈",
    recordedAt: "2026-11-08T07:30:00+09:00", status: "images_ready", video: null,
    originalText: "학교에서 친구를 만나 바다를 보러 갔어요. 낯선 마을을 지나 오래된 집에 도착했는데, 누군가 저를 부르는 것 같았어요.",
    scenes: [
      scene("school", "school", "학교", "학교 운동장", "학교에 도착해서 친구를 만났어요. 꽃이 핀 나무와 익숙한 교실 창문이 보였고, 날씨는 따뜻했어요.", [["학교 건물", "high"], ["함께 있던 친구", "medium"], ["따뜻한 햇빛", "high"]]),
      scene("sea", "sea", "바다", "바닷가 산책로", "친구와 함께 바다를 보러 갔어요. 난간 너머로 잔잔한 파도가 보였고, 하늘은 연한 분홍빛이었어요.", [["잔잔한 바다", "high"], ["분홍빛 하늘", "medium"], ["친구의 얼굴", "low"]]),
      scene("village", "village", "낯선 마을", "마을 골목", "작은 집들이 모인 골목을 걸었어요. 창문마다 불이 켜져 있었지만, 어디로 가고 있었는지는 잘 기억나지 않아요.", [["창문에 켜진 불빛", "medium"], ["골목의 방향", "low"], ["조용했던 기분", "medium"]]),
      scene("house", "house", "오래된 집", "정원이 있는 집", "꽃이 핀 정원을 지나 오래된 집 앞에 도착했어요. 문이 열려 있었고, 안에서 익숙한 목소리가 들렸어요.", [["꽃이 핀 정원", "high"], ["열려 있던 문", "high"], ["집 안의 목소리", "low"]]),
      scene("person", "person", "나를 부른 사람", "집 앞", "누군가 저를 부르는 것 같아 뒤를 돌아봤어요. 그 사람이 누구였는지, 어떤 말을 했는지는 흐릿해요.", [["뒤에 있던 사람", "low"], ["목소리", "low"], ["익숙한 느낌", "medium"]]),
    ],
  },
  {
    id: "demo-evening", title: "불빛을 따라 걷던 저녁",
    recordedAt: "2026-11-06T08:10:00+09:00", status: "images_ready", video: null,
    originalText: "저녁 무렵 마을을 걷다가 정원이 있는 집을 찾았어요. 마지막에는 바다가 보였어요.",
    scenes: [
      scene("evening-village", "village", "저녁 골목", "마을 골목", "불빛이 하나둘 켜지는 마을을 천천히 걸었어요. 발소리가 들렸고 마음은 편안했어요.", [["창문의 불빛", "high"], ["발소리", "medium"]]),
      scene("evening-house", "house", "정원이 있는 집", "작은 정원", "정원에 꽃이 많이 피어 있었어요. 문 앞에 잠깐 서 있었던 것 같은데, 누구를 기다렸는지는 기억나지 않아요.", [["정원의 꽃", "high"], ["기다리던 사람", "low"]]),
      scene("evening-sea", "sea", "밤이 오기 전 바다", "바닷가", "골목이 끝나자 바다가 나타났어요. 멀리 달이 떠 있었고 물결은 아주 잔잔했어요.", [["달빛", "high"], ["잔잔한 물결", "medium"]]),
    ],
  },
];
