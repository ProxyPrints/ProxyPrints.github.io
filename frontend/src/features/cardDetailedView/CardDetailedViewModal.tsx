/**
 * If the user clicks a card in the project editor, this component will be displayed,
 * which is a modal that shows a higher-resolution version of the card,
 * some more information (e.g. size, dote uploaded, etc.), and a button to download the full res image.
 *
 * The editor-completion package's §7.5/R3 extraction (E6/X5) moved this modal's own right-column
 * body content out into CardDetailedViewBody.tsx's region-level sub-blocks, so the /display left
 * rail's demoted Card Details/Printing Tags/Report sections can mount the same content
 * individually (see that file's own module comment). This component's render below is
 * deliberately unchanged in shape - same Modal chrome, same left-column image, same right-column
 * content, now sourced from CardDetailedViewBody rather than inlined - so
 * tests/visual/CardDetailedViewModal.visual.spec.ts's aria snapshot keeps passing unmodified,
 * which is this extraction's own acceptance test.
 */

import React, { memo } from "react";
import Button from "react-bootstrap/Button";
import Modal from "react-bootstrap/Modal";
import Row from "react-bootstrap/Row";

import { getCardDataAttributes } from "@/common/cardDom";
import { CardDocument } from "@/common/types";
import DisableSSR from "@/components/DisableSSR";
import {
  MemoizedCardImage,
  MemoizedCardProportionWrapper,
} from "@/features/card/Card";
import { CardDetailedViewBody } from "@/features/cardDetailedView/CardDetailedViewBody";

interface CardDetailedViewProps {
  cardDocument: CardDocument;
  show: boolean;
  handleClose: {
    (): void;
    (event: React.MouseEvent<HTMLButtonElement, MouseEvent>): void;
  };
}

export function CardDetailedViewModal({
  cardDocument,
  show,
  handleClose,
}: CardDetailedViewProps) {
  return (
    <DisableSSR>
      <Modal
        show={show}
        onHide={handleClose}
        size={"xl"}
        data-testid="detailed-view"
        {...getCardDataAttributes(cardDocument)}
      >
        <Modal.Header closeButton>
          <Modal.Title>Card Details</Modal.Title>
        </Modal.Header>
        <Modal.Body>
          <Row>
            <div
              className="col-lg-5 mb-3 mb-lg-0"
              style={{ position: "relative" }}
            >
              <MemoizedCardProportionWrapper small={false}>
                <MemoizedCardImage
                  cardDocument={cardDocument}
                  hidden={false}
                  small={false}
                  showDetailedViewOnClick={false}
                />
              </MemoizedCardProportionWrapper>
            </div>
            <div className="col-lg-7">
              <CardDetailedViewBody cardDocument={cardDocument} />
            </div>
          </Row>
        </Modal.Body>
        <Modal.Footer>
          <Button variant="secondary" onClick={handleClose}>
            Close
          </Button>
        </Modal.Footer>
      </Modal>
    </DisableSSR>
  );
}

export const MemoizedCardDetailedView = memo(CardDetailedViewModal);
