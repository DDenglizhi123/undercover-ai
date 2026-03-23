# chat/views.py
from django.shortcuts import render

def room(request, room_name):
    # Renders the HTML page and passes the room_name to the template
    return render(request, 'chat/room.html', {
        'room_name': room_name
    })