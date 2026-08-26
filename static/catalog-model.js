import {naturalVolumeCompare} from "./formatters.js";

export function editionRelations(edition) {
  return (edition.work_relations || []).map((relation) => ({
    work_id: Number(relation.work_id),
    relation_type: relation.relation_type === 'volume' ? 'volume' : 'contained',
    volume_id: relation.relation_type === 'volume'
      ? Number(relation.volume_id || 0) || null : null
  }));
}

export function groupedVolumes(group) {
  return (group.volumes || []).map((item) => (
    item.volume ? {id: item.id, ...item.volume, copies: item.copies || []} : item
  )).sort((left, right) =>
    (left.position ?? 0) - (right.position ?? 0)
    || naturalVolumeCompare(left.volume_number || '', right.volume_number || '')
  );
}

export function groupCopies(group) {
  return groupedVolumes(group).flatMap((volume) => volume.copies || []);
}
