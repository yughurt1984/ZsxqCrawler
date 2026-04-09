'use client';

import GroupSelector from '@/components/GroupSelector';
import { useRouter } from 'next/navigation';

export default function Home() {
  const router = useRouter();

  return (
    <GroupSelector
      onGroupSelected={(group) => router.push(`/groups/${group.group_id}`)}
    />
  );
}
