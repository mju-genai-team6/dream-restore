import DreamResults from "@/features/dream-results/DreamResults";

export default async function Home({ searchParams }: PageProps<"/">) {
  const query = await searchParams;
  const single = (value: string | string[] | undefined) => Array.isArray(value) ? value[0] : value;
  return <DreamResults dreamId={single(query.dreamId)} jobId={single(query.jobId)} view={single(query.view)} />;
}
