import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React from "react";
import { Provider } from "react-redux";

import { CardType, Project, SlotProjectMembers } from "@/common/types";
import { ApplySiblingImageAffordance } from "@/features/card/ApplySiblingImageAffordance";
import { setupStore } from "@/store/store";

const baseProjectState: Project = {
  members: [],
  nextMemberId: 0,
  cardback: null,
  mostRecentlySelectedSlot: null,
  manualOverrides: {},
};

function frontMember(
  id: string,
  query: string,
  selectedImage: string | undefined
): SlotProjectMembers {
  return {
    id,
    front: {
      query: { query, cardType: "CARD" as CardType },
      selectedImage,
      selected: false,
    },
    back: null,
  };
}

function renderAffordance(members: Array<SlotProjectMembers>, slot = 0) {
  const store = setupStore({
    project: { ...baseProjectState, members },
  });
  render(
    <Provider store={store}>
      <ApplySiblingImageAffordance face="front" slot={slot} />
    </Provider>
  );
  return store;
}

describe("ApplySiblingImageAffordance", () => {
  test("renders nothing when there are no siblings to update", () => {
    renderAffordance([frontMember("t-0", "Lightning Bolt", "bolt-art-a")]);
    expect(screen.queryByTestId("apply-sibling-image-front0")).toBeNull();
  });

  test("offers to apply the image to sibling slots that don't have one selected yet", () => {
    renderAffordance([
      frontMember("t-0", "Lightning Bolt", "bolt-art-a"),
      frontMember("t-1", "Lightning Bolt", undefined),
      frontMember("t-2", "Counterspell", undefined),
    ]);
    expect(
      screen.getByTestId("apply-sibling-image-button-front0")
    ).toHaveTextContent("Apply to 1 other copy");
    expect(screen.queryByTestId("apply-sibling-image-note-front0")).toBeNull();
  });

  test("clicking applies the image to unset siblings only, leaving a different card's slots untouched", async () => {
    const user = userEvent.setup();
    const store = renderAffordance([
      frontMember("t-0", "Lightning Bolt", "bolt-art-a"),
      frontMember("t-1", "Lightning Bolt", undefined),
      frontMember("t-2", "Counterspell", undefined),
    ]);

    await user.click(screen.getByTestId("apply-sibling-image-button-front0"));

    expect(
      store
        .getState()
        .project.members.map((member) => member.front?.selectedImage)
    ).toStrictEqual(["bolt-art-a", "bolt-art-a", undefined]);
  });

  test("surfaces a note when a sibling already has a different image, and never overwrites it", async () => {
    const user = userEvent.setup();
    const store = renderAffordance([
      frontMember("t-0", "Lightning Bolt", "bolt-art-a"),
      frontMember("t-1", "Lightning Bolt", "bolt-art-b"),
      frontMember("t-2", "Lightning Bolt", undefined),
    ]);

    expect(
      screen.getByTestId("apply-sibling-image-note-front0")
    ).toHaveTextContent("1 other copy keeps its own art");

    await user.click(screen.getByTestId("apply-sibling-image-button-front0"));

    expect(
      store
        .getState()
        .project.members.map((member) => member.front?.selectedImage)
    ).toStrictEqual(["bolt-art-a", "bolt-art-b", "bolt-art-a"]);
  });
});
