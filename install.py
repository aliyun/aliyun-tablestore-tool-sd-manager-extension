import launch

if not launch.is_installed("tablestore"):
    launch.run_pip("install tablestore", "requirements for tablestore-sd-manager-extension")

if not launch.is_installed("wordcloud"):
    launch.run_pip("install wordcloud", "requirements for tablestore-sd-manager-extension")
