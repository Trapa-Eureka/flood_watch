import EventForm from "./_components/EventForm";
import EventPipelineList from "./_components/EventPipelineList";

export const metadata = { title: "PH Flood Watch — Admin" };

export default function AdminPage() {
  return (
    <>
      <EventForm />
      <EventPipelineList />
    </>
  );
}
