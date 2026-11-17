import TranscriptStep from "@/features/dream-record/TranscriptStep";

export default async function Page({ params }: PageProps<"/record/[dreamId]/transcript">) {
  const { dreamId } = await params;
  return <TranscriptStep dreamId={dreamId} />;
}
