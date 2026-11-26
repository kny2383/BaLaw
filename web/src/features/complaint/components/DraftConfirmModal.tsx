import React, { useState } from 'react';

import Button from '@/shared/ui/common/Button';

import type { DraftClaim } from '@/features/complaint/apis/complaints';

type DraftConfirmModalProps = {
  claims: DraftClaim[];
  isSubmitting: boolean;
  errorMessage: string | null;
  onSubmit: (answers: boolean[]) => void;
};

/**
 * 초안에서 대화로 확인되지 않은 표현을 사용자에게 묻는다.
 * 사실이 맞다고 답한 표현은 초안에 남고, 아니라고 답한 표현은 고쳐 쓴다.
 */
const DraftConfirmModal: React.FC<DraftConfirmModalProps> = ({
  claims,
  isSubmitting,
  errorMessage,
  onSubmit,
}) => {
  const [answers, setAnswers] = useState<(boolean | null)[]>(() => claims.map(() => null));

  const allAnswered = answers.every((a) => a !== null);

  const choose = (index: number, value: boolean) => {
    setAnswers((prev) => prev.map((a, i) => (i === index ? value : a)));
  };

  return (
    <div
      className="animate-overlay-in fixed inset-0 z-50 flex items-center justify-center bg-neutral-900/40 px-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="draft-confirm-title"
    >
      <div className="animate-pop-in flex max-h-[85vh] w-full max-w-xl flex-col rounded-2xl bg-white shadow-[0_16px_40px_rgba(15,23,42,0.2)]">
        <div className="shrink-0 px-8 pt-8 pb-4">
          <h2
            id="draft-confirm-title"
            className="text-body-1-bold text-neutral-900"
          >
            초안의 내용이 맞는지 확인해 주세요
          </h2>
          <p className="text-body-3-regular mt-2 text-neutral-500">
            아래 표현은 대화에서 말씀하신 내용으로 확인되지 않았어요. 실제로 겪은 일이 맞으면
            &lsquo;맞아요&rsquo;를, 아니면 &lsquo;아니에요&rsquo;를 골라 주세요. 아니라고 답한
            표현은 초안에서 고쳐 써요.
          </p>
        </div>

        <ul className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto px-8 py-2">
          {claims.map((claim, index) => (
            <li
              key={index}
              className="rounded-xl border border-neutral-200 bg-neutral-50 px-4 py-4"
            >
              <p className="text-body-3-bold leading-relaxed text-neutral-800">
                &ldquo;{claim.quote}&rdquo;
              </p>
              {claim.reason && (
                <p className="text-detail-regular mt-2 leading-relaxed text-neutral-500">
                  확인이 필요한 이유: {claim.reason}
                </p>
              )}
              <div
                className="mt-3 flex gap-2"
                role="group"
                aria-label={`${index + 1}번 표현이 사실인지 선택`}
              >
                {[
                  { value: true, label: '맞아요' },
                  { value: false, label: '아니에요' },
                ].map((option) => {
                  const selected = answers[index] === option.value;
                  return (
                    <button
                      key={option.label}
                      type="button"
                      aria-pressed={selected}
                      disabled={isSubmitting}
                      onClick={() => choose(index, option.value)}
                      className={[
                        'text-body-3-regular rounded-lg border px-4 py-2 transition-colors disabled:opacity-60',
                        selected
                          ? 'border-primary-400 bg-primary-0 text-primary-600'
                          : 'border-neutral-200 bg-white text-neutral-600 hover:border-neutral-300',
                      ].join(' ')}
                    >
                      {option.label}
                    </button>
                  );
                })}
              </div>
            </li>
          ))}
        </ul>

        <div className="shrink-0 px-8 pt-4 pb-8">
          {errorMessage && (
            <p
              role="alert"
              className="text-detail-regular text-warning-300 mb-3"
            >
              {errorMessage}
            </p>
          )}
          <Button
            variant="primary"
            size="md"
            fullWidth
            disabled={!allAnswered || isSubmitting}
            onClick={() => onSubmit(answers.map((a) => a === true))}
          >
            {isSubmitting ? '초안을 정리하고 있어요' : '답변 보내기'}
          </Button>
        </div>
      </div>
    </div>
  );
};

export default DraftConfirmModal;
