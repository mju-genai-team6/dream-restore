import InterviewStep from "@/features/dream-record/InterviewStep";

export default async function Page({ params }: PageProps<"/record/[dreamId]/interview">) {
  const { dreamId } = await params;
  return <InterviewStep dreamId={dreamId} />;
}
