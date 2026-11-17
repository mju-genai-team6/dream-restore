import ResumeStep from "@/features/dream-record/ResumeStep";

export default async function Page({ params }: PageProps<"/record/[dreamId]">) {
  const { dreamId } = await params;
  return <ResumeStep dreamId={dreamId} />;
}
