import ConfidenceStep from "@/features/dream-record/ConfidenceStep";

export default async function Page({ params }: PageProps<"/record/[dreamId]/confidence">) {
  const { dreamId } = await params;
  return <ConfidenceStep dreamId={dreamId} />;
}
