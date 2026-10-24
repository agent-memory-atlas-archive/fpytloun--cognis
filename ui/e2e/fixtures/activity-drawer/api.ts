export const api = {
  conversations: {
    async backgroundCommand(conversationId: string, shellId: string) {
      const response = await fetch(`/api/v1/conversations/${conversationId}/background-commands/${shellId}`);
      if (!response.ok) throw new Error('Background command is no longer available');
      return response.json();
    },
  },
};
